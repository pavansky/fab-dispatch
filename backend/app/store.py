"""Persistence behind one small repository interface.

* ``SQLiteStore``   local default: zero setup, a file under ./data (or :memory: in tests)
* ``PostgresStore`` production: any Postgres, including Supabase (use the pooled URL)

Both share one schema, applied idempotently at startup (``CREATE TABLE IF NOT EXISTS``),
so a fresh database needs no migration step. Three things are stored:

* ``shifts``       live-shift state, one JSON document per shift with an optimistic
                   ``version``. Writers must quote the version they read, so two
                   dispatchers can't silently overwrite each other (HTTP 409 instead).
* ``shift_events`` append-only event log per shift. The SSE stream tails it by id, which
                   makes reconnects (Last-Event-ID) and multiple server instances just work.
* ``plan_cache``   content-addressed solver results (key = hash of the inputs). Solvers
                   are deterministic, so a hit is always valid. This is the cache tier
                   shared across serverless instances.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings


class VersionConflict(Exception):
    """The shift changed since the caller read it."""


class NotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store(ABC):
    kind: str

    @abstractmethod
    def init_schema(self) -> None: ...
    @abstractmethod
    def ping(self) -> bool: ...
    @abstractmethod
    def create_shift(self, shift_id: str, state: dict) -> None: ...
    @abstractmethod
    def get_shift(self, shift_id: str) -> tuple[dict, int]: ...
    @abstractmethod
    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int: ...
    @abstractmethod
    def list_shifts(self, limit: int = 20) -> list[dict]: ...
    @abstractmethod
    def append_events(self, shift_id: str, events: list[dict]) -> list[int]: ...
    @abstractmethod
    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]: ...
    @abstractmethod
    def get_cached_plan(self, key: str) -> Any | None: ...
    @abstractmethod
    def put_cached_plan(self, key: str, value: Any) -> None: ...


# ----------------------------------------------------------------------------- SQLite
class SQLiteStore(Store):
    kind = "sqlite"

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shift_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, shift_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS shift_events_by_shift ON shift_events (shift_id, id);
                CREATE TABLE IF NOT EXISTS plan_cache (
                    key TEXT PRIMARY KEY, created_at TEXT NOT NULL, value TEXT NOT NULL);
            """)

    def ping(self) -> bool:
        return self._q("SELECT 1")[0][0] == 1

    def create_shift(self, shift_id: str, state: dict) -> None:
        now = _now()
        self._q("INSERT INTO shifts (id, version, created_at, updated_at, state) VALUES (?, 1, ?, ?, ?)",
                (shift_id, now, now, json.dumps(state)))

    def get_shift(self, shift_id: str) -> tuple[dict, int]:
        rows = self._q("SELECT state, version FROM shifts WHERE id = ?", (shift_id,))
        if not rows:
            raise NotFound(shift_id)
        return json.loads(rows[0]["state"]), rows[0]["version"]

    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE shifts SET state = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?",
                (json.dumps(state), _now(), shift_id, expected_version))
            if cur.rowcount != 1:
                raise VersionConflict(shift_id)
        return expected_version + 1

    def list_shifts(self, limit: int = 20) -> list[dict]:
        rows = self._q("SELECT id, version, created_at, updated_at FROM shifts ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def append_events(self, shift_id: str, events: list[dict]) -> list[int]:
        ids = []
        with self._lock:
            for e in events:
                cur = self._conn.execute(
                    "INSERT INTO shift_events (shift_id, created_at, kind, payload) VALUES (?, ?, ?, ?)",
                    (shift_id, _now(), e["kind"], json.dumps(e)))
                ids.append(cur.lastrowid)
        return ids

    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]:
        rows = self._q("SELECT id, payload FROM shift_events WHERE shift_id = ? AND id > ? ORDER BY id LIMIT ?",
                       (shift_id, after_id, limit))
        return [{"id": r["id"], **json.loads(r["payload"])} for r in rows]

    def get_cached_plan(self, key: str) -> Any | None:
        rows = self._q("SELECT value FROM plan_cache WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def put_cached_plan(self, key: str, value: Any) -> None:
        self._q("INSERT OR IGNORE INTO plan_cache (key, created_at, value) VALUES (?, ?, ?)",
                (key, _now(), json.dumps(value)))


# ----------------------------------------------------------------------------- Postgres
class PostgresStore(Store):
    """psycopg 3, one short connection per call. That suits serverless functions sitting
    behind Supabase's transaction pooler, where prepared statements must be off."""

    kind = "postgres"

    def __init__(self, url: str):
        import psycopg  # imported lazily: local SQLite runs never need the driver
        from psycopg.rows import dict_row

        self._psycopg, self._dict_row, self._url = psycopg, dict_row, url

    def _conn(self):
        return self._psycopg.connect(self._url, autocommit=True, prepare_threshold=None,
                                     row_factory=self._dict_row, connect_timeout=5)

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else []

    def init_schema(self) -> None:
        self._q("""
            CREATE TABLE IF NOT EXISTS shifts (
                id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), state JSONB NOT NULL);
            CREATE TABLE IF NOT EXISTS shift_events (
                id BIGSERIAL PRIMARY KEY, shift_id TEXT NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(), kind TEXT NOT NULL, payload JSONB NOT NULL);
            CREATE INDEX IF NOT EXISTS shift_events_by_shift ON shift_events (shift_id, id);
            CREATE TABLE IF NOT EXISTS plan_cache (
                key TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), value JSONB NOT NULL);
        """)

    def ping(self) -> bool:
        return self._q("SELECT 1 AS ok")[0]["ok"] == 1

    def create_shift(self, shift_id: str, state: dict) -> None:
        self._q("INSERT INTO shifts (id, version, state) VALUES (%s, 1, %s)", (shift_id, json.dumps(state)))

    def get_shift(self, shift_id: str) -> tuple[dict, int]:
        rows = self._q("SELECT state, version FROM shifts WHERE id = %s", (shift_id,))
        if not rows:
            raise NotFound(shift_id)
        return rows[0]["state"], rows[0]["version"]

    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int:
        rows = self._q("UPDATE shifts SET state = %s, version = version + 1, updated_at = now() "
                       "WHERE id = %s AND version = %s RETURNING version",
                       (json.dumps(state), shift_id, expected_version))
        if not rows:
            raise VersionConflict(shift_id)
        return rows[0]["version"]

    def list_shifts(self, limit: int = 20) -> list[dict]:
        rows = self._q("SELECT id, version, created_at, updated_at FROM shifts ORDER BY created_at DESC LIMIT %s", (limit,))
        return [{**r, "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()} for r in rows]

    def append_events(self, shift_id: str, events: list[dict]) -> list[int]:
        ids = []
        with self._conn() as c, c.cursor() as cur:
            for e in events:
                cur.execute("INSERT INTO shift_events (shift_id, kind, payload) VALUES (%s, %s, %s) RETURNING id",
                            (shift_id, e["kind"], json.dumps(e)))
                ids.append(cur.fetchone()["id"])
        return ids

    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]:
        rows = self._q("SELECT id, payload FROM shift_events WHERE shift_id = %s AND id > %s ORDER BY id LIMIT %s",
                       (shift_id, after_id, limit))
        return [{"id": r["id"], **r["payload"]} for r in rows]

    def get_cached_plan(self, key: str) -> Any | None:
        rows = self._q("SELECT value FROM plan_cache WHERE key = %s", (key,))
        return rows[0]["value"] if rows else None

    def put_cached_plan(self, key: str, value: Any) -> None:
        self._q("INSERT INTO plan_cache (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(value)))


def create_store(settings: Settings) -> Store:
    if settings.is_postgres:
        store: Store = PostgresStore(settings.database_url)
    else:
        store = SQLiteStore(settings.database_url.removeprefix("sqlite:///"))
    store.init_schema()
    return store
