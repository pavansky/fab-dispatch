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
* ``assignments``     read model: one row per known job of each live shift (engineer, times,
                      status), projected from the shift state in the same transaction as each
                      write. The JSON document stays the write model; this makes the domain
                      queryable ("what did E03 work on?") without parsing documents.
* ``rate_limits``     per-minute request counters shared by every instance, so a quota holds
                      on serverless, where each instance would otherwise count alone.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import zlib
from abc import ABC, abstractmethod
from collections.abc import Collection
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
    (
        4,
        "assistant answer feedback",
        {
            # Thumbs up/down on assistant answers: the evaluation loop for answers in production.
            # Stores the user id, never the email; closed to the Supabase API like every app table.
            "sqlite": [
                """CREATE TABLE IF NOT EXISTS assistant_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT,
               created_at TEXT NOT NULL, user_id TEXT NOT NULL, intent TEXT NOT NULL, helpful INTEGER NOT NULL,
               question TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', citations TEXT NOT NULL DEFAULT '[]',
               provider TEXT NOT NULL DEFAULT 'local')""",
                "CREATE INDEX IF NOT EXISTS assistant_feedback_by_time ON assistant_feedback (created_at)",
            ],
            "postgres": [
                """CREATE TABLE IF NOT EXISTS assistant_feedback (id BIGSERIAL PRIMARY KEY,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), user_id TEXT NOT NULL, intent TEXT NOT NULL,
               helpful BOOLEAN NOT NULL, question TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
               citations JSONB NOT NULL DEFAULT '[]', provider TEXT NOT NULL DEFAULT 'local')""",
                "CREATE INDEX IF NOT EXISTS assistant_feedback_by_time ON assistant_feedback (created_at)",
                "ALTER TABLE assistant_feedback ENABLE ROW LEVEL SECURITY",
                """DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
                     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON assistant_feedback FROM anon, authenticated;
                    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM anon, authenticated',
                                   pg_get_serial_sequence('assistant_feedback', 'id'));
                  END IF;
                END $$""",
            ],
        },
    ),
]
MIGRATIONS.append(
    (
        5,
        "assignments read model, shared rate limits",
        {
            "sqlite": [
                """CREATE TABLE IF NOT EXISTS assignments (shift_id TEXT NOT NULL, job_id TEXT NOT NULL,
               fab_id TEXT NOT NULL, engineer_id TEXT, status TEXT NOT NULL, skill TEXT NOT NULL,
               priority INTEGER NOT NULL, tool TEXT NOT NULL DEFAULT '', start_min REAL, end_min REAL,
               updated_at TEXT NOT NULL, PRIMARY KEY (shift_id, job_id))""",
                "CREATE INDEX IF NOT EXISTS assignments_by_engineer ON assignments (fab_id, engineer_id, updated_at)",
                """CREATE TABLE IF NOT EXISTS rate_limits (key TEXT NOT NULL, window_start INTEGER NOT NULL,
               hits INTEGER NOT NULL, PRIMARY KEY (key, window_start))""",
            ],
            "postgres": [
                """CREATE TABLE IF NOT EXISTS assignments (shift_id TEXT NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
               job_id TEXT NOT NULL, fab_id TEXT NOT NULL, engineer_id TEXT, status TEXT NOT NULL,
               skill TEXT NOT NULL, priority INTEGER NOT NULL, tool TEXT NOT NULL DEFAULT '',
               start_min DOUBLE PRECISION, end_min DOUBLE PRECISION,
               updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (shift_id, job_id))""",
                "CREATE INDEX IF NOT EXISTS assignments_by_engineer ON assignments (fab_id, engineer_id, updated_at DESC)",
                """CREATE TABLE IF NOT EXISTS rate_limits (key TEXT NOT NULL, window_start BIGINT NOT NULL,
               hits INTEGER NOT NULL, PRIMARY KEY (key, window_start))""",
                "ALTER TABLE assignments ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY",
                """DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
                     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON assignments, rate_limits FROM anon, authenticated;
                  END IF;
                END $$""",
            ],
        },
    )
)
SCHEMA_VERSION = MIGRATIONS[-1][0]
# Every table the app owns: schema-qualified on Postgres, and closed to the Supabase Data API.
APP_TABLES = (
    "shifts",
    "shift_events",
    "plan_cache",
    "idempotency_keys",
    "shift_presence",
    "assistant_feedback",
    "assignments",
    "rate_limits",
    "schema_migrations",
)
PRESENCE_WINDOW_S = 30
FEEDBACK_DAYS = 180  # assistant feedback retention
DELETED_USER = "a deleted user"
ASSIGNMENT_COLUMNS = ("job_id", "engineer_id", "status", "skill", "priority", "tool", "start_min", "end_min")


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
    def create_shift(
        self, shift_id: str, state: dict, fab_id: str, created_by: str, assignments: list[dict] | None = None
    ) -> None: ...
    @abstractmethod
    def get_shift(self, shift_id: str, fabs: Collection[str] | None = None) -> tuple[dict, int]:
        """The shift's state and version. ``fabs`` scopes the read in SQL to the caller's fabs
        (None = unscoped, for trusted internal use): a shift in another fab is NotFound."""

    @abstractmethod
    def save_shift(
        self, shift_id: str, state: dict, expected_version: int, assignments: list[dict] | None = None
    ) -> int:
        """Version-checked write. ``assignments`` replaces the shift's read-model rows in the
        same transaction, so the read model never disagrees with the document."""

    @abstractmethod
    def shift_assignments(self, shift_id: str) -> list[dict]: ...
    @abstractmethod
    def engineer_assignments(self, fab_id: str, engineer_id: str, limit: int = 100) -> list[dict]: ...
    @abstractmethod
    def hit_rate(self, key: str, window_s: int = 60) -> int:
        """Count one request against ``key`` in the current window; return the window's total."""

    @abstractmethod
    def delete_user_data(self, user_id: str, email: str) -> dict[str, int]:
        """Erase a user's personal data: their feedback, presence and pending replays are
        deleted; their email in shift history is replaced, keeping the audit trail's shape."""

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

    @abstractmethod
    def add_feedback(self, record: dict) -> None: ...

    @abstractmethod
    def feedback_stats(self, days: int = 30) -> list[dict]: ...

    def delete_auth_user(self, user_id: str) -> bool:
        """Remove the sign-in account itself, where the store also holds accounts (Supabase)."""
        return False

    def close(self) -> None:
        """Release held connections (Postgres opens one per call, so holds none)."""
        return None

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

    def close(self) -> None:
        with self._lock:
            self._conn.close()

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

    def _project(self, shift_id: str, fab_id: str, rows: list[dict]) -> None:
        """Replace the shift's read-model rows. Caller holds the lock inside a transaction."""
        self._conn.execute("DELETE FROM assignments WHERE shift_id = ?", (shift_id,))
        now = _now()
        self._conn.executemany(
            "INSERT INTO assignments (shift_id, fab_id, updated_at, " + ", ".join(ASSIGNMENT_COLUMNS) + ") "
            "VALUES (?, ?, ?, " + ", ".join("?" * len(ASSIGNMENT_COLUMNS)) + ")",
            [(shift_id, fab_id, now, *(r[c] for c in ASSIGNMENT_COLUMNS)) for r in rows],
        )

    def create_shift(
        self, shift_id: str, state: dict, fab_id: str, created_by: str, assignments: list[dict] | None = None
    ) -> None:
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO shifts (id, version, created_at, updated_at, state, fab_id, created_by) "
                    "VALUES (?, 1, ?, ?, ?, ?, ?)",
                    (shift_id, now, now, json.dumps(state), fab_id, created_by),
                )
                if assignments is not None:
                    self._project(shift_id, fab_id, assignments)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_shift(self, shift_id: str, fabs: Collection[str] | None = None) -> tuple[dict, int]:
        sql, args = "SELECT state, version FROM shifts WHERE id = ?", [shift_id]
        if fabs is not None and "*" not in fabs:
            sql += f" AND fab_id IN ({', '.join('?' * len(fabs))})" if fabs else " AND 0"
            args += list(fabs)
        rows = self._q(sql, tuple(args))
        if not rows:
            raise NotFound(shift_id)
        return json.loads(rows[0]["state"]), rows[0]["version"]

    def save_shift(
        self, shift_id: str, state: dict, expected_version: int, assignments: list[dict] | None = None
    ) -> int:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                cur = self._conn.execute(
                    "UPDATE shifts SET state = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ? "
                    "RETURNING fab_id",
                    (json.dumps(state), _now(), shift_id, expected_version),
                )
                row = cur.fetchone()
                if row is None:
                    raise VersionConflict(shift_id)
                if assignments is not None:
                    self._project(shift_id, row["fab_id"], assignments)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return expected_version + 1

    def shift_assignments(self, shift_id: str) -> list[dict]:
        rows = self._q(
            "SELECT " + ", ".join(ASSIGNMENT_COLUMNS) + " FROM assignments WHERE shift_id = ? ORDER BY job_id",
            (shift_id,),
        )
        return [dict(r) for r in rows]

    def engineer_assignments(self, fab_id: str, engineer_id: str, limit: int = 100) -> list[dict]:
        rows = self._q(
            "SELECT shift_id, updated_at, " + ", ".join(ASSIGNMENT_COLUMNS) + " FROM assignments "
            "WHERE fab_id = ? AND engineer_id = ? ORDER BY updated_at DESC, start_min LIMIT ?",
            (fab_id, engineer_id, limit),
        )
        return [dict(r) for r in rows]

    def hit_rate(self, key: str, window_s: int = 60) -> int:
        window = int(datetime.now(UTC).timestamp()) // window_s * window_s
        rows = self._q(
            "INSERT INTO rate_limits (key, window_start, hits) VALUES (?, ?, 1) "
            "ON CONFLICT (key, window_start) DO UPDATE SET hits = hits + 1 RETURNING hits",
            (key, window),
        )
        return rows[0]["hits"]

    def delete_user_data(self, user_id: str, email: str) -> dict[str, int]:
        replace_actor = (
            "json_set(payload, '$.actor', ?, '$.message', replace(json_extract(payload, '$.message'), ?, ?))"
        )
        with self._lock:
            out = {
                "assistant_feedback": self._conn.execute(
                    "DELETE FROM assistant_feedback WHERE user_id = ?", (user_id,)
                ).rowcount,
                "shift_presence": self._conn.execute(
                    "DELETE FROM shift_presence WHERE user_id = ?", (user_id,)
                ).rowcount,
                "idempotency_keys": self._conn.execute(
                    "DELETE FROM idempotency_keys WHERE key LIKE ?", (f"{user_id}:%",)
                ).rowcount,
                "shift_events": self._conn.execute(
                    f"UPDATE shift_events SET payload = {replace_actor} WHERE json_extract(payload, '$.actor') = ?",
                    (DELETED_USER, email, DELETED_USER, email),
                ).rowcount,
                "shifts": self._conn.execute(
                    "UPDATE shifts SET created_by = ?, state = json_set(state, '$.created_by', ?) WHERE created_by = ?",
                    (DELETED_USER, DELETED_USER, email),
                ).rowcount,
            }
            self._conn.execute(
                "UPDATE shifts SET state = json_set(state, '$.driver', NULL) WHERE json_extract(state, '$.driver') = ?",
                (email,),
            )
        return out

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
            out["assistant_feedback"] = self._conn.execute(
                "DELETE FROM assistant_feedback WHERE created_at < ?", (_ago(FEEDBACK_DAYS * 86400),)
            ).rowcount
            out["assignments"] = self._conn.execute(
                "DELETE FROM assignments WHERE shift_id NOT IN (SELECT id FROM shifts)"
            ).rowcount
            out["rate_limits"] = self._conn.execute(
                "DELETE FROM rate_limits WHERE window_start < ?", (int(datetime.now(UTC).timestamp()) - 3600,)
            ).rowcount
        return out

    def add_feedback(self, record: dict) -> None:
        self._q(
            """INSERT INTO assistant_feedback (created_at, user_id, intent, helpful, question, comment, citations,
               provider) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _now(),
                record["user_id"],
                record["intent"],
                int(record["helpful"]),
                record["question"],
                record.get("comment", ""),
                json.dumps(record.get("citations", [])),
                record.get("provider", "local"),
            ),
        )

    def feedback_stats(self, days: int = 30) -> list[dict]:
        rows = self._q(
            """SELECT intent, COUNT(*) AS total, SUM(helpful) AS helpful FROM assistant_feedback
               WHERE created_at >= ? GROUP BY intent ORDER BY total DESC""",
            (_ago(days * 86400),),
        )
        return [{"intent": r["intent"], "total": r["total"], "helpful": r["helpful"] or 0} for r in rows]


# ----------------------------------------------------------------------------- Postgres
_TABLES = re.compile(r"\b(" + "|".join(APP_TABLES) + r")\b")


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

    def _project(self, cur, shift_id: str, fab_id: str, rows: list[dict]) -> None:
        """Replace the shift's read-model rows on the caller's transaction."""
        cur.execute(self._sql("DELETE FROM assignments WHERE shift_id = %s"), (shift_id,))
        if rows:
            cur.executemany(
                self._sql(
                    "INSERT INTO assignments (shift_id, fab_id, " + ", ".join(ASSIGNMENT_COLUMNS) + ") "
                    "VALUES (%s, %s, " + ", ".join(["%s"] * len(ASSIGNMENT_COLUMNS)) + ")"
                ),
                [(shift_id, fab_id, *(r[c] for c in ASSIGNMENT_COLUMNS)) for r in rows],
            )

    def create_shift(
        self, shift_id: str, state: dict, fab_id: str, created_by: str, assignments: list[dict] | None = None
    ) -> None:
        with self._conn(autocommit=False) as c, c.cursor() as cur:
            cur.execute(
                self._sql("INSERT INTO shifts (id, version, state, fab_id, created_by) VALUES (%s, 1, %s, %s, %s)"),
                (shift_id, json.dumps(state), fab_id, created_by),
            )
            if assignments is not None:
                self._project(cur, shift_id, fab_id, assignments)
            c.commit()

    def get_shift(self, shift_id: str, fabs: Collection[str] | None = None) -> tuple[dict, int]:
        if fabs is None or "*" in fabs:
            rows = self._q("SELECT state, version FROM shifts WHERE id = %s", (shift_id,))
        else:
            rows = self._q(
                "SELECT state, version FROM shifts WHERE id = %s AND fab_id = ANY(%s)", (shift_id, list(fabs))
            )
        if not rows:
            raise NotFound(shift_id)
        return rows[0]["state"], rows[0]["version"]

    def save_shift(
        self, shift_id: str, state: dict, expected_version: int, assignments: list[dict] | None = None
    ) -> int:
        with self._conn(autocommit=False) as c, c.cursor() as cur:
            cur.execute(
                self._sql(
                    "UPDATE shifts SET state = %s, version = version + 1, updated_at = now() "
                    "WHERE id = %s AND version = %s RETURNING version, fab_id"
                ),
                (json.dumps(state), shift_id, expected_version),
            )
            row = cur.fetchone()
            if row is None:
                raise VersionConflict(shift_id)
            if assignments is not None:
                self._project(cur, shift_id, row["fab_id"], assignments)
            c.commit()
        return row["version"]

    def shift_assignments(self, shift_id: str) -> list[dict]:
        return self._q(
            "SELECT " + ", ".join(ASSIGNMENT_COLUMNS) + " FROM assignments WHERE shift_id = %s ORDER BY job_id",
            (shift_id,),
        )

    def engineer_assignments(self, fab_id: str, engineer_id: str, limit: int = 100) -> list[dict]:
        rows = self._q(
            "SELECT shift_id, updated_at, " + ", ".join(ASSIGNMENT_COLUMNS) + " FROM assignments "
            "WHERE fab_id = %s AND engineer_id = %s ORDER BY updated_at DESC, start_min LIMIT %s",
            (fab_id, engineer_id, limit),
        )
        return [{**r, "updated_at": r["updated_at"].isoformat()} for r in rows]

    def hit_rate(self, key: str, window_s: int = 60) -> int:
        rows = self._q(
            "INSERT INTO rate_limits AS r (key, window_start, hits) "
            "VALUES (%s, (extract(epoch FROM now())::bigint / %s) * %s, 1) "
            "ON CONFLICT (key, window_start) DO UPDATE SET hits = r.hits + 1 RETURNING hits",
            (key, window_s, window_s),
        )
        return rows[0]["hits"]

    def delete_user_data(self, user_id: str, email: str) -> dict[str, int]:
        out = {}
        with self._conn(autocommit=False) as c, c.cursor() as cur:
            for table, sql, args in (
                ("assistant_feedback", "DELETE FROM assistant_feedback WHERE user_id = %s", (user_id,)),
                ("shift_presence", "DELETE FROM shift_presence WHERE user_id = %s", (user_id,)),
                ("idempotency_keys", "DELETE FROM idempotency_keys WHERE key LIKE %s", (f"{user_id}:%",)),
                (
                    "shift_events",
                    "UPDATE shift_events SET payload = payload || jsonb_build_object('actor', %s::text, "
                    "'message', replace(payload->>'message', %s, %s)) WHERE payload->>'actor' = %s",
                    (DELETED_USER, email, DELETED_USER, email),
                ),
                (
                    "shifts",
                    "UPDATE shifts SET created_by = %s, state = state || jsonb_build_object('created_by', %s::text) "
                    "WHERE created_by = %s",
                    (DELETED_USER, DELETED_USER, email),
                ),
            ):
                cur.execute(self._sql(sql), args)
                out[table] = cur.rowcount
            cur.execute(
                self._sql("UPDATE shifts SET state = state || '{\"driver\": null}'::jsonb WHERE state->>'driver' = %s"),
                (email,),
            )
            c.commit()
        return out

    def delete_auth_user(self, user_id: str) -> bool:
        """On Supabase, remove the sign-in account itself (auth.users). False elsewhere."""
        if not re.fullmatch(r"[0-9a-f-]{36}", user_id):
            return False
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT to_regclass('auth.users') IS NOT NULL AS ok")
            if not cur.fetchone()["ok"]:
                return False
            cur.execute("DELETE FROM auth.users WHERE id = %s::uuid", (user_id,))
            return cur.rowcount == 1

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
                (
                    "assistant_feedback",
                    "DELETE FROM assistant_feedback WHERE created_at < now() - make_interval(days => %s)",
                    FEEDBACK_DAYS,
                ),
                (
                    "rate_limits",
                    "DELETE FROM rate_limits WHERE window_start < extract(epoch FROM now())::bigint - %s",
                    3600,
                ),
            ):
                cur.execute(self._sql(sql), (arg,))
                out[table] = cur.rowcount
        return out

    def add_feedback(self, record: dict) -> None:
        self._q(
            """INSERT INTO assistant_feedback (user_id, intent, helpful, question, comment, citations, provider)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                record["user_id"],
                record["intent"],
                bool(record["helpful"]),
                record["question"],
                record.get("comment", ""),
                json.dumps(record.get("citations", [])),
                record.get("provider", "local"),
            ),
        )

    def feedback_stats(self, days: int = 30) -> list[dict]:
        rows = self._q(
            """SELECT intent, COUNT(*) AS total, COUNT(*) FILTER (WHERE helpful) AS helpful
               FROM assistant_feedback WHERE created_at >= now() - make_interval(days => %s)
               GROUP BY intent ORDER BY total DESC""",
            (days,),
        )
        return [{"intent": r["intent"], "total": r["total"], "helpful": r["helpful"]} for r in rows]


def open_store(url: str, schema: str = "public") -> Store:
    """A migrated store for one database URL (the default database, or one fab's own)."""
    store: Store = (
        PostgresStore(url, schema) if url.startswith("postgres") else SQLiteStore(url.removeprefix("sqlite:///"))
    )
    store.migrate()
    return store


def create_store(settings: Settings) -> Store:
    return open_store(settings.database_url, settings.db_schema)
