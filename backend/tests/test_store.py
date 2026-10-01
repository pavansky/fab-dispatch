"""The same contract against every store backend. Postgres runs when FAB_TEST_PG_URL is set
(CI starts a postgres:16 service; locally: docker run postgres:16-alpine)."""

import os
import uuid

import pytest

from app.store import NotFound, PostgresStore, SQLiteStore, VersionConflict

PG_URL = os.environ.get("FAB_TEST_PG_URL")


def _stores():
    yield pytest.param(lambda: SQLiteStore(":memory:"), id="sqlite")
    yield pytest.param(
        lambda: PostgresStore(PG_URL),
        id="postgres",
        marks=pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set"),
    )


@pytest.fixture(params=list(_stores()))
def store(request):
    s = request.param()
    s.init_schema()
    s.init_schema()  # idempotent
    return s


def test_shift_roundtrip_and_optimistic_versioning(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {"clock": 0}, "fab1-300mm-logic", "a@b.c")
    state, v = store.get_shift(sid)
    assert state == {"clock": 0} and v == 1
    assert store.save_shift(sid, {"clock": 30}, 1) == 2
    with pytest.raises(VersionConflict):
        store.save_shift(sid, {"clock": 99}, 1)  # stale writer loses
    assert store.get_shift(sid) == ({"clock": 30}, 2)
    assert any(s["id"] == sid and s["created_by"] == "a@b.c" for s in store.list_shifts("fab1-300mm-logic", 50))
    assert all(s["id"] != sid for s in store.list_shifts("fab2-200mm-analog", 50))
    with pytest.raises(NotFound):
        store.get_shift("missing-" + sid)


def test_event_log_is_ordered_and_resumable(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {}, "fab1-300mm-logic", "")
    ids = store.append_events(sid, [{"kind": "a", "n": 1}, {"kind": "b", "n": 2}, {"kind": "c", "n": 3}])
    assert ids == sorted(ids)
    assert [e["kind"] for e in store.events_after(sid, 0)] == ["a", "b", "c"]
    assert [e["kind"] for e in store.events_after(sid, ids[0])] == ["b", "c"]
    assert store.events_after(sid, ids[-1]) == []


def test_plan_cache_is_write_once(store):
    key = uuid.uuid4().hex
    assert store.get_cached_plan(key) is None
    store.put_cached_plan(key, {"v": 1})
    store.put_cached_plan(key, {"v": 2})  # content-addressed: first write wins
    assert store.get_cached_plan(key) == {"v": 1}
    assert store.ping()


@pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set")
def test_environments_in_separate_schemas_never_see_each_other():
    prod, uat = PostgresStore(PG_URL, "public"), PostgresStore(PG_URL, "uat_test")
    prod.migrate()
    uat.migrate()
    sid = uuid.uuid4().hex[:12]
    uat.create_shift(sid, {"env": "uat"}, "fab1-300mm-logic", "tester@x")
    assert uat.get_shift(sid)[0] == {"env": "uat"}
    with pytest.raises(NotFound):
        prod.get_shift(sid)
    assert uat.schema_version() == prod.schema_version()


def test_schema_names_are_validated():
    with pytest.raises(ValueError):
        PostgresStore("postgresql://x", 'uat"; drop table shifts; --')


@pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set")
def test_app_tables_are_closed_to_the_supabase_api_roles():
    """Supabase grants its public API roles access to new tables by default; migration 3 must
    take that away (RLS on, grants revoked) while the service itself keeps working."""
    import psycopg

    schema = f"rls_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(PG_URL, autocommit=True) as c:
        for role in ("anon", "authenticated"):
            c.execute(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        c.execute(f'CREATE SCHEMA "{schema}"')
        c.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO anon, authenticated')
        c.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON TABLES TO anon, authenticated')
        c.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON SEQUENCES TO anon, authenticated')

    store = PostgresStore(PG_URL, schema)
    store.migrate()
    tables = ["shifts", "shift_events", "plan_cache", "idempotency_keys", "shift_presence", "schema_migrations"]
    with psycopg.connect(PG_URL) as c:
        for t in tables:
            rls = c.execute(
                "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f'"{schema}".{t}',)
            ).fetchone()[0]
            assert rls, f"{t}: row-level security is off"
            for role in ("anon", "authenticated"):
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    has = c.execute(
                        "SELECT has_table_privilege(%s, %s, %s)", (role, f'"{schema}".{t}', priv)
                    ).fetchone()[0]
                    assert not has, f"{role} can {priv} {t}"
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {"ok": True}, "fab1-300mm-logic", "svc@x")  # the service still reads and writes
    assert store.get_shift(sid)[0] == {"ok": True}
    assert store.schema_version() == 3
