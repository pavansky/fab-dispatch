"""The same contract against every store backend. Postgres runs when FAB_TEST_PG_URL is set
(CI starts a postgres:16 service; locally: docker run postgres:16-alpine)."""
import os
import uuid

import pytest

from app.store import NotFound, PostgresStore, SQLiteStore, VersionConflict

PG_URL = os.environ.get("FAB_TEST_PG_URL")


def _stores():
    yield pytest.param(lambda: SQLiteStore(":memory:"), id="sqlite")
    yield pytest.param(lambda: PostgresStore(PG_URL), id="postgres",
                       marks=pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set"))


@pytest.fixture(params=list(_stores()))
def store(request):
    s = request.param()
    s.init_schema()
    s.init_schema()  # idempotent
    return s


def test_shift_roundtrip_and_optimistic_versioning(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {"clock": 0})
    state, v = store.get_shift(sid)
    assert state == {"clock": 0} and v == 1
    assert store.save_shift(sid, {"clock": 30}, 1) == 2
    with pytest.raises(VersionConflict):
        store.save_shift(sid, {"clock": 99}, 1)        # stale writer loses
    assert store.get_shift(sid) == ({"clock": 30}, 2)
    assert any(s["id"] == sid for s in store.list_shifts(50))
    with pytest.raises(NotFound):
        store.get_shift("missing-" + sid)


def test_event_log_is_ordered_and_resumable(store):
    sid = uuid.uuid4().hex[:12]
    store.create_shift(sid, {})
    ids = store.append_events(sid, [{"kind": "a", "n": 1}, {"kind": "b", "n": 2}, {"kind": "c", "n": 3}])
    assert ids == sorted(ids)
    assert [e["kind"] for e in store.events_after(sid, 0)] == ["a", "b", "c"]
    assert [e["kind"] for e in store.events_after(sid, ids[0])] == ["b", "c"]
    assert store.events_after(sid, ids[-1]) == []


def test_plan_cache_is_write_once(store):
    key = uuid.uuid4().hex
    assert store.get_cached_plan(key) is None
    store.put_cached_plan(key, {"v": 1})
    store.put_cached_plan(key, {"v": 2})   # content-addressed: first write wins
    assert store.get_cached_plan(key) == {"v": 1}
    assert store.ping()
