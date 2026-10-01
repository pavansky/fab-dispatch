"""The same contract against every store backend. Postgres runs when FAB_TEST_PG_URL is set
(CI starts a postgres:16 service; locally: docker run postgres:16-alpine)."""

import os
import uuid

import pytest

from app.store import APP_TABLES, SCHEMA_VERSION, NotFound, PostgresStore, SQLiteStore, VersionConflict

PG_URL = os.environ.get("FAB_TEST_PG_URL")


def _stores():
    yield pytest.param(lambda: SQLiteStore(":memory:"), id="sqlite")
    yield pytest.param(
        lambda: PostgresStore(PG_URL, f"t_{uuid.uuid4().hex[:8]}"),  # a fresh schema: tests never share rows
        id="postgres",
        marks=pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set"),
    )


@pytest.fixture(params=list(_stores()))
def store(request):
    s = request.param()
    s.init_schema()
    s.init_schema()  # idempotent
    yield s
    if isinstance(s, PostgresStore):
        import psycopg

        with psycopg.connect(PG_URL, autocommit=True) as c:
            c.execute(f'DROP SCHEMA "{s.schema}" CASCADE')


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
    tables = APP_TABLES
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
    assert store.schema_version() == SCHEMA_VERSION


def test_feedback_is_stored_counted_and_pruned(store):
    store.add_feedback(
        {"user_id": "u1", "intent": "job", "helpful": True, "question": "why J006?", "citations": ["floor-plan"]}
    )
    store.add_feedback(
        {"user_id": "u2", "intent": "job", "helpful": False, "question": "why J007?", "comment": "wrong"}
    )
    store.add_feedback({"user_id": "u1", "intent": "docs", "helpful": True, "question": "idle wait?"})
    stats = {r["intent"]: r for r in store.feedback_stats(30)}
    assert stats["job"]["total"] == 2 and stats["job"]["helpful"] == 1
    assert stats["docs"] == {"intent": "docs", "total": 1, "helpful": 1}
    assert store.prune()["assistant_feedback"] == 0  # all recent: nothing to delete


def test_reads_are_scoped_to_the_callers_fabs(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {"n": 1}, "fab1-300mm-logic", "a@b.c")
    assert store.get_shift(sid, fabs=["fab1-300mm-logic"])[0] == {"n": 1}
    assert store.get_shift(sid, fabs=["*"])[0] == {"n": 1}
    for scope in (["fab2-200mm-specialty"], []):
        with pytest.raises(NotFound):
            store.get_shift(sid, fabs=scope)


def test_read_model_rows_are_written_with_the_document(store):
    sid = uuid.uuid4().hex[:12]
    row = {
        "job_id": "J1",
        "engineer_id": "E1",
        "status": "planned",
        "skill": "etch",
        "priority": 2,
        "tool": "T",
        "start_min": 10.0,
        "end_min": 70.0,
    }
    store.create_shift(sid, {"v": 1}, "fab1-300mm-logic", "a@b.c", assignments=[row])
    assert store.shift_assignments(sid) == [row]
    store.save_shift(sid, {"v": 2}, 1, assignments=[{**row, "engineer_id": "E2"}, {**row, "job_id": "J2"}])
    assert [r["engineer_id"] for r in store.shift_assignments(sid)] == ["E2", "E1"]
    assert [r["job_id"] for r in store.engineer_assignments("fab1-300mm-logic", "E2")] == ["J1"]
    # A lost race writes neither the document nor the read model.
    with pytest.raises(VersionConflict):
        store.save_shift(sid, {"v": 3}, 1, assignments=[])
    assert len(store.shift_assignments(sid)) == 2


def test_rate_counters_are_shared_per_window(store):
    key = f"k-{uuid.uuid4().hex[:6]}"
    assert [store.hit_rate(key) for _ in range(3)] == [1, 2, 3]
    assert store.hit_rate(f"{key}-other") == 1


def test_user_data_is_erased_and_history_anonymised(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {"created_by": "x@y.z", "driver": "x@y.z"}, "fab1-300mm-logic", "x@y.z")
    store.append_events(sid, [{"kind": "started", "actor": "x@y.z", "message": "x@y.z started the shift."}])
    store.add_feedback({"user_id": "ux", "intent": "job", "helpful": True, "question": "q"})
    store.touch_presence(sid, "ux", "x@y.z")
    store.put_idempotent(f"ux:{sid}:k", {"ok": 1})
    out = store.delete_user_data("ux", "x@y.z")
    assert out == {"assistant_feedback": 1, "shift_presence": 1, "idempotency_keys": 1, "shift_events": 1, "shifts": 1}
    event = store.events_after(sid, 0)[0]
    assert event["actor"] == "a deleted user" and event["message"] == "a deleted user started the shift."
    state = store.get_shift(sid)[0]
    assert state["created_by"] == "a deleted user" and state["driver"] is None
    assert store.presence(sid) == [] and store.get_idempotent(f"ux:{sid}:k") is None
