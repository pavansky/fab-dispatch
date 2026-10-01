"""Persistence behind one small repository interface.

* ``SQLiteStore``   local default: zero setup, a file under ./data (or :memory: in tests)
* ``PostgresStore`` UAT/production: any Postgres, including Supabase (use the pooled URL)

Schema changes are **versioned migrations** (``MIGRATIONS`` below), applied in order at
startup and recorded in ``schema_migrations``. On Postgres they run under an advisory
lock, so concurrent serverless cold starts can't race. Migrations are append-only:
never edit a released one, add the next number.

What is stored:

* ``shifts``          live-shift state, one JSON document per shift with an optimistic
                      ``version``, scoped to a fab and recording who created it.
* ``shift_events``    append-only event log per shift (the audit trail). The SSE stream
                      tails it by id, so reconnects and multiple instances just work.
* ``plan_cache``      content-addressed solver results, shared across instances.
* ``idempotency_keys`` responses to mutating requests, so a retried request (flaky
                      network, double click) is answered once, not applied twice.
* ``shift_presence``  who has a live shift open right now.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import zlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings

# (version, name, {dialect: [statements]}). Append only.
MIGRATIONS: list[tuple[int, str, dict[str, list[str]]]] = [
    (
        1,
        "initial schema",
        {
            "sqlite": [
                """CREATE TABLE IF NOT EXISTS shifts (id TEXT PRIMARY KEY, version INTEGER NOT NULL,
               created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS shift_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
               shift_id TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)""",
                "CREATE INDEX IF NOT EXISTS shift_events_by_shift ON shift_events (shift_id, id)",
                "CREATE TABLE IF NOT EXISTS plan_cache (key TEXT PRIMARY KEY, created_at TEXT NOT NULL, value TEXT NOT NULL)",
            ],
            "postgres": [
                """CREATE TABLE IF NOT EXISTS shifts (id TEXT PRIMARY KEY, version INTEGER NOT NULL,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               state JSONB NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS shift_events (id BIGSERIAL PRIMARY KEY,
               shift_id TEXT NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), kind TEXT NOT NULL, payload JSONB NOT NULL)""",
                "CREATE INDEX IF NOT EXISTS shift_events_by_shift ON shift_events (shift_id, id)",
                """CREATE TABLE IF NOT EXISTS plan_cache (key TEXT PRIMARY KEY,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), value JSONB NOT NULL)""",
            ],
        },
    ),
    (
        2,
        "fab tenancy, idempotency keys, presence",
        {
            "sqlite": [
                "ALTER TABLE shifts ADD COLUMN fab_id TEXT NOT NULL DEFAULT 'fab1-300mm-logic'",
                "ALTER TABLE shifts ADD COLUMN created_by TEXT NOT NULL DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS shifts_by_fab ON shifts (fab_id, created_at)",
                """CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT NOT NULL,
               response TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS shift_presence (shift_id TEXT NOT NULL, user_id TEXT NOT NULL,
               email TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY (shift_id, user_id))""",
            ],
            "postgres": [
                "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS fab_id TEXT NOT NULL DEFAULT 'fab1-300mm-logic'",
                "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS shifts_by_fab ON shifts (fab_id, created_at DESC)",
                """CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), response JSONB NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS shift_presence (shift_id TEXT NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
               user_id TEXT NOT NULL, email TEXT NOT NULL, last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
               PRIMARY KEY (shift_id, user_id))""",
            ],
        },
    ),
    (
        3,
        "lock app tables away from the Supabase Data API",
        {
            # Supabase exposes tables in its API schemas to the public `anon` and `authenticated`
            # roles, and grants them access to new tables by default. Only this service (which
            # connects as the table owner, so RLS doesn't apply to it) may touch app data: enable
            # RLS with no policies, and revoke the API roles' grants. No-op where they don't exist.
            "sqlite": [],
            "postgres": [
                *(
                    f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"
                    for t in (
                        "shifts",
                        "shift_events",
                        "plan_cache",
                        "idempotency_keys",
                        "shift_presence",
                        "schema_migrations",
                    )
                ),
                """DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
                     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON shifts, shift_events, plan_cache, idempotency_keys, shift_presence,
                      schema_migrations FROM anon, authenticated;
                    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM anon, authenticated',
                                   pg_get_serial_sequence('shift_events', 'id'));
                  END IF;
                END $$""",
            ],
        },
    ),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]
PRESENCE_WINDOW_S = 30


class VersionConflict(Exception):
    """The shift changed since the caller read it."""


class NotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


class Store(ABC):
    kind: str

    @abstractmethod
    def migrate(self) -> list[int]: ...
    @abstractmethod
    def schema_version(self) -> int: ...
    @abstractmethod
    def ping(self) -> bool: ...
    @abstractmethod
    def create_shift(self, shift_id: str, state: dict, fab_id: str, created_by: str) -> None: ...
    @abstractmethod
    def get_shift(self, shift_id: str) -> tuple[dict, int]: ...
    @abstractmethod
    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int: ...
    @abstractmethod
    def list_shifts(self, fab_id: str, limit: int = 20) -> list[dict]: ...
    @abstractmethod
    def append_events(self, shift_id: str, events: list[dict]) -> list[int]: ...
    @abstractmethod
    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]: ...
    @abstractmethod
    def get_cached_plan(self, key: str) -> Any | None: ...
    @abstractmethod
    def put_cached_plan(self, key: str, value: Any) -> None: ...
    @abstractmethod
    def get_idempotent(self, key: str) -> Any | None: ...
    @abstractmethod
    def put_idempotent(self, key: str, response: Any) -> None: ...
    @abstractmethod
    def touch_presence(self, shift_id: str, user_id: str, email: str) -> None: ...
    @abstractmethod
    def presence(self, shift_id: str) -> list[str]: ...
    @abstractmethod
    def prune(self, plan_days: int = 7, shift_days: int = 30, idempotency_hours: int = 24) -> dict[str, int]: ...

    def init_schema(self) -> None:
        """Alias kept for call sites written before versioned migrations."""
        self.migrate()


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

    def migrate(self) -> list[int]:
        applied = []
        with self._lock:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,
                                  name TEXT NOT NULL, applied_at TEXT NOT NULL)""")
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for version, name, sql in MIGRATIONS:
                if version in done:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for stmt in sql["sqlite"]:
                        try:
                            self._conn.execute(stmt)
                        except sqlite3.OperationalError as e:
                            # Databases created before versioned migrations may already have a column.
                            if "duplicate column" not in str(e):
                                raise
                    self._conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (version, name, _now()))
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                applied.append(version)
        return applied

    def schema_version(self) -> int:
        return self._q("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")[0][0]

    def ping(self) -> bool:
        return self._q("SELECT 1")[0][0] == 1

    def create_shift(self, shift_id: str, state: dict, fab_id: str, created_by: str) -> None:
        now = _now()
        self._q(
            "INSERT INTO shifts (id, version, created_at, updated_at, state, fab_id, created_by) "
            "VALUES (?, 1, ?, ?, ?, ?, ?)",
            (shift_id, now, now, json.dumps(state), fab_id, created_by),
        )

    def get_shift(self, shift_id: str) -> tuple[dict, int]:
        rows = self._q("SELECT state, version FROM shifts WHERE id = ?", (shift_id,))
        if not rows:
            raise NotFound(shift_id)
        return json.loads(rows[0]["state"]), rows[0]["version"]

    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE shifts SET state = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?",
                (json.dumps(state), _now(), shift_id, expected_version),
            )
            if cur.rowcount != 1:
                raise VersionConflict(shift_id)
        return expected_version + 1

    def list_shifts(self, fab_id: str, limit: int = 20) -> list[dict]:
        rows = self._q(
            "SELECT id, version, created_at, updated_at, created_by, json_extract(state, '$.clock') AS clock, "
            "json_extract(state, '$.algorithm') AS algorithm, json_extract(state, '$.ended') AS ended "
            "FROM shifts WHERE fab_id = ? ORDER BY created_at DESC LIMIT ?",
            (fab_id, limit),
        )
        return [{**dict(r), "ended": bool(r["ended"])} for r in rows]

    def append_events(self, shift_id: str, events: list[dict]) -> list[int]:
        ids = []
        with self._lock:
            for e in events:
                cur = self._conn.execute(
                    "INSERT INTO shift_events (shift_id, created_at, kind, payload) VALUES (?, ?, ?, ?)",
                    (shift_id, _now(), e["kind"], json.dumps(e)),
                )
                ids.append(cur.lastrowid)
        return ids

    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]:
        rows = self._q(
            "SELECT id, payload FROM shift_events WHERE shift_id = ? AND id > ? ORDER BY id LIMIT ?",
            (shift_id, after_id, limit),
        )
        return [{"id": r["id"], **json.loads(r["payload"])} for r in rows]

    def get_cached_plan(self, key: str) -> Any | None:
        rows = self._q("SELECT value FROM plan_cache WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def put_cached_plan(self, key: str, value: Any) -> None:
        self._q(
            "INSERT OR IGNORE INTO plan_cache (key, created_at, value) VALUES (?, ?, ?)",
            (key, _now(), json.dumps(value)),
        )

    def get_idempotent(self, key: str) -> Any | None:
        rows = self._q("SELECT response FROM idempotency_keys WHERE key = ?", (key,))
        return json.loads(rows[0]["response"]) if rows else None

    def put_idempotent(self, key: str, response: Any) -> None:
        self._q(
            "INSERT OR IGNORE INTO idempotency_keys (key, created_at, response) VALUES (?, ?, ?)",
            (key, _now(), json.dumps(response)),
        )

    def touch_presence(self, shift_id: str, user_id: str, email: str) -> None:
        self._q(
            "INSERT INTO shift_presence (shift_id, user_id, email, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (shift_id, user_id) DO UPDATE SET last_seen = excluded.last_seen",
            (shift_id, user_id, email, _now()),
        )

    def presence(self, shift_id: str) -> list[str]:
        rows = self._q(
            "SELECT email FROM shift_presence WHERE shift_id = ? AND last_seen > ? ORDER BY email",
            (shift_id, _ago(PRESENCE_WINDOW_S)),
        )
        return [r["email"] for r in rows]

    def prune(self, plan_days: int = 7, shift_days: int = 30, idempotency_hours: int = 24) -> dict[str, int]:
        with self._lock:
            out = {
                "plan_cache": self._conn.execute(
                    "DELETE FROM plan_cache WHERE created_at < ?", (_ago(plan_days * 86400),)
                ).rowcount,
                "idempotency_keys": self._conn.execute(
                    "DELETE FROM idempotency_keys WHERE created_at < ?", (_ago(idempotency_hours * 3600),)
                ).rowcount,
            }
            old = [
                r[0]
                for r in self._conn.execute("SELECT id FROM shifts WHERE updated_at < ?", (_ago(shift_days * 86400),))
            ]
            for sid in old:
                self._conn.execute("DELETE FROM shift_events WHERE shift_id = ?", (sid,))
                self._conn.execute("DELETE FROM shift_presence WHERE shift_id = ?", (sid,))
                self._conn.execute("DELETE FROM shifts WHERE id = ?", (sid,))
            out["shifts"] = len(old)
            out["shift_presence"] = self._conn.execute(
                "DELETE FROM shift_presence WHERE last_seen < ?", (_ago(86400),)
            ).rowcount
        return out


# ----------------------------------------------------------------------------- Postgres
_TABLES = re.compile(r"\b(shifts|shift_events|plan_cache|idempotency_keys|shift_presence|schema_migrations)\b")


class PostgresStore(Store):
    """psycopg 3, one short connection per call. That suits serverless functions sitting
    behind Supabase's transaction pooler, where prepared statements must be off.

    Every table is qualified with ``schema`` (``FAB_DB_SCHEMA``), so environments can share
    one database without seeing each other's data (e.g. UAT in schema ``uat``). Qualifying
    names, rather than ``SET search_path``, is safe behind a transaction pooler, where a
    session setting could leak onto another client's connection."""

    kind = "postgres"
    MIGRATION_LOCK = 724_311  # base advisory-lock id; offset per schema

    def __init__(self, url: str, schema: str = "public"):
        import psycopg  # imported lazily: local SQLite runs never need the driver
        from psycopg.rows import dict_row

        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self._psycopg, self._dict_row, self._url = psycopg, dict_row, url
        self.schema = schema
        self._lock_id = self.MIGRATION_LOCK + zlib.crc32(schema.encode()) % 1_000_000

    def _sql(self, sql: str) -> str:
        return _TABLES.sub(lambda m: f'"{self.schema}".{m.group(1)}', sql)

    def _conn(self, autocommit: bool = True):
        return self._psycopg.connect(
            self._url, autocommit=autocommit, prepare_threshold=None, row_factory=self._dict_row, connect_timeout=5
        )

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(self._sql(sql), args)
            return cur.fetchall() if cur.description else []

    def migrate(self) -> list[int]:
        applied = []
        with self._conn(autocommit=False) as c, c.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock_id,))
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cur.execute(
                self._sql("""CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,
                           name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            )
            cur.execute(self._sql("SELECT version FROM schema_migrations"))
            done = {r["version"] for r in cur.fetchall()}
            for version, name, sql in MIGRATIONS:
                if version in done:
                    continue
                for stmt in sql["postgres"]:
                    cur.execute(self._sql(stmt))
                cur.execute(self._sql("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)"), (version, name))
                applied.append(version)
            c.commit()
        return applied

    def schema_version(self) -> int:
        return self._q("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations")[0]["v"]

    def ping(self) -> bool:
        return self._q("SELECT 1 AS ok")[0]["ok"] == 1

    def create_shift(self, shift_id: str, state: dict, fab_id: str, created_by: str) -> None:
        self._q(
            "INSERT INTO shifts (id, version, state, fab_id, created_by) VALUES (%s, 1, %s, %s, %s)",
            (shift_id, json.dumps(state), fab_id, created_by),
        )

    def get_shift(self, shift_id: str) -> tuple[dict, int]:
        rows = self._q("SELECT state, version FROM shifts WHERE id = %s", (shift_id,))
        if not rows:
            raise NotFound(shift_id)
        return rows[0]["state"], rows[0]["version"]

    def save_shift(self, shift_id: str, state: dict, expected_version: int) -> int:
        rows = self._q(
            "UPDATE shifts SET state = %s, version = version + 1, updated_at = now() "
            "WHERE id = %s AND version = %s RETURNING version",
            (json.dumps(state), shift_id, expected_version),
        )
        if not rows:
            raise VersionConflict(shift_id)
        return rows[0]["version"]

    def list_shifts(self, fab_id: str, limit: int = 20) -> list[dict]:
        rows = self._q(
            "SELECT id, version, created_at, updated_at, created_by, (state->>'clock')::float AS clock, "
            "state->>'algorithm' AS algorithm, COALESCE((state->>'ended')::boolean, false) AS ended "
            "FROM shifts WHERE fab_id = %s ORDER BY created_at DESC LIMIT %s",
            (fab_id, limit),
        )
        return [
            {**r, "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()} for r in rows
        ]

    def append_events(self, shift_id: str, events: list[dict]) -> list[int]:
        ids = []
        with self._conn() as c, c.cursor() as cur:
            for e in events:
                cur.execute(
                    self._sql("INSERT INTO shift_events (shift_id, kind, payload) VALUES (%s, %s, %s) RETURNING id"),
                    (shift_id, e["kind"], json.dumps(e)),
                )
                ids.append(cur.fetchone()["id"])
        return ids

    def events_after(self, shift_id: str, after_id: int, limit: int = 200) -> list[dict]:
        rows = self._q(
            "SELECT id, payload FROM shift_events WHERE shift_id = %s AND id > %s ORDER BY id LIMIT %s",
            (shift_id, after_id, limit),
        )
        return [{"id": r["id"], **r["payload"]} for r in rows]

    def get_cached_plan(self, key: str) -> Any | None:
        rows = self._q("SELECT value FROM plan_cache WHERE key = %s", (key,))
        return rows[0]["value"] if rows else None

    def put_cached_plan(self, key: str, value: Any) -> None:
        self._q(
            "INSERT INTO plan_cache (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (key, json.dumps(value))
        )

    def get_idempotent(self, key: str) -> Any | None:
        rows = self._q("SELECT response FROM idempotency_keys WHERE key = %s", (key,))
        return rows[0]["response"] if rows else None

    def put_idempotent(self, key: str, response: Any) -> None:
        self._q(
            "INSERT INTO idempotency_keys (key, response) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (key, json.dumps(response)),
        )

    def touch_presence(self, shift_id: str, user_id: str, email: str) -> None:
        self._q(
            "INSERT INTO shift_presence (shift_id, user_id, email, last_seen) VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (shift_id, user_id) DO UPDATE SET last_seen = now(), email = excluded.email",
            (shift_id, user_id, email),
        )

    def presence(self, shift_id: str) -> list[str]:
        rows = self._q(
            "SELECT email FROM shift_presence WHERE shift_id = %s "
            "AND last_seen > now() - make_interval(secs => %s) ORDER BY email",
            (shift_id, PRESENCE_WINDOW_S),
        )
        return [r["email"] for r in rows]

    def prune(self, plan_days: int = 7, shift_days: int = 30, idempotency_hours: int = 24) -> dict[str, int]:
        out = {}
        with self._conn() as c, c.cursor() as cur:
            for table, sql, arg in (
                (
                    "plan_cache",
                    "DELETE FROM plan_cache WHERE created_at < now() - make_interval(days => %s)",
                    plan_days,
                ),
                (
                    "idempotency_keys",
                    "DELETE FROM idempotency_keys WHERE created_at < now() - make_interval(hours => %s)",
                    idempotency_hours,
                ),
                ("shifts", "DELETE FROM shifts WHERE updated_at < now() - make_interval(days => %s)", shift_days),
                ("shift_presence", "DELETE FROM shift_presence WHERE last_seen < now() - make_interval(days => %s)", 1),
            ):
                cur.execute(self._sql(sql), (arg,))
                out[table] = cur.rowcount
        return out


def create_store(settings: Settings) -> Store:
    if settings.is_postgres:
        store: Store = PostgresStore(settings.database_url, settings.db_schema)
    else:
        store = SQLiteStore(settings.database_url.removeprefix("sqlite:///"))
    store.migrate()
    return store
