"""Real-time production behaviours: idempotency, clock lease, presence, audit, retention, migrations."""

import sqlite3

from fastapi.testclient import TestClient

from app.auth import issue_demo_token
from app.config import get_settings
from app.main import app
from app.store import SCHEMA_VERSION, SQLiteStore
from tests.conftest import auth_headers

alice = TestClient(app, headers=auth_headers("dispatcher"))


def _other_dispatcher() -> TestClient:
    # A second dispatcher identity (different user id) for lease tests.
    import jwt

    s = get_settings()
    claims = jwt.decode(issue_demo_token("dispatcher", s), s.auth_secret, algorithms=["HS256"], audience="fab-dispatch")
    claims |= {"sub": "demo-dispatcher-2", "email": "dispatcher2@demo.local"}
    return TestClient(app, headers={"Authorization": f"Bearer {jwt.encode(claims, s.auth_secret)}"})


def _shift() -> str:
    sc = alice.post("/api/scenario", json={"seed": 9, "n_engineers": 6, "n_jobs": 16}).json()
    return alice.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]


def test_idempotency_key_applies_a_retried_request_once():
    sid = _shift()
    first = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers={"Idempotency-Key": "k1"}).json()
    again = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers={"Idempotency-Key": "k1"}).json()
    assert again["idempotent_replay"] is True
    assert again["state"]["clock"] == first["state"]["clock"] == 60  # not 120
    assert alice.get(f"/api/shifts/{sid}").json()["state"]["clock"] == 60


def test_concurrent_requests_with_one_idempotency_key_apply_once(monkeypatch):
    """Both requests pass the replay check before either writes: the key, claimed in the write's
    transaction, still lets only one of them apply."""
    import threading

    from app import live

    sid = _shift()
    both_read = threading.Barrier(2, timeout=10)
    real_advance = live.advance
    attempts = []

    def advance_after_both_read(state, minutes, actor="system"):
        attempts.append(minutes)
        if len(attempts) <= 2:  # the first attempt of each request: both have read version 1
            both_read.wait()
        return real_advance(state, minutes, actor)

    monkeypatch.setattr(live, "advance", advance_after_both_read)
    results = []

    def call():
        r = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers={"Idempotency-Key": "race"})
        results.append(r)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert [r.status_code for r in results] == [200, 200]
    bodies = [r.json() for r in results]
    assert sorted(b.get("idempotent_replay", False) for b in bodies) == [False, True]
    assert {b["version"] for b in bodies} == {2} and {b["state"]["clock"] for b in bodies} == {60}
    got = alice.get(f"/api/shifts/{sid}").json()
    assert got["version"] == 2 and got["state"]["clock"] == 60  # applied once: not version 3, not 120 min
    assert sum(e["kind"] == "clock" for e in alice.get(f"/api/shifts/{sid}/events").json()) == 1


def test_a_write_that_fails_part_way_is_applied_once_on_retry(monkeypatch):
    """Events are written in the same transaction as the shift: if appending them fails, the
    version bump and the idempotency key roll back too, so the client's retry applies once."""
    from app.deps import store_for_shift

    sid = _shift()
    store = store_for_shift(sid)
    real_insert = store._insert_events
    calls = {"n": 0}

    def fail_once(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection lost while appending events")
        return real_insert(*args)

    monkeypatch.setattr(store, "_insert_events", fail_once)
    headers = {"Idempotency-Key": "flaky"}
    assert alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers=headers).status_code == 500
    assert alice.get(f"/api/shifts/{sid}").json()["version"] == 1  # nothing half-written
    retry = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers=headers).json()
    assert retry["version"] == 2 and retry["state"]["clock"] == 60 and "idempotent_replay" not in retry
    again = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers=headers).json()
    assert again["idempotent_replay"] is True and again["state"]["clock"] == 60


def test_the_etag_of_a_shift_works_as_its_if_match():
    sid = _shift()
    got = alice.get(f"/api/shifts/{sid}")
    tag = got.headers["etag"]
    assert tag.startswith(f'"{got.json()["version"]}-')
    ok = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}, headers={"If-Match": tag})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}, headers={"If-Match": tag})
    assert stale.status_code == 409  # the shift moved on since that read
    off = alice.post(f"/api/shifts/{sid}/engineers/E01/off", headers={"If-Match": '"2"'})  # a quoted version
    assert off.status_code == 200 and off.json()["version"] == 3
    for pinned in ("3", 'W/"3-abc"', '"1-x", "3-y"', "*"):  # repeats are no-ops: still version 3
        assert alice.post(f"/api/shifts/{sid}/engineers/E01/off", headers={"If-Match": pinned}).status_code == 200
    assert alice.post(f"/api/shifts/{sid}/engineers/E01/off", headers={"If-Match": '"2"'}).status_code == 409
    fresh = alice.get(f"/api/shifts/{sid}")
    assert alice.get(f"/api/shifts/{sid}", headers={"If-None-Match": fresh.headers["etag"]}).status_code == 304


def test_a_conditional_get_still_sees_presence_change_without_a_new_version():
    sid = _shift()
    before = alice.get(f"/api/shifts/{sid}")
    viewer = TestClient(app, headers=auth_headers("viewer"))
    token = issue_demo_token("viewer", get_settings())
    with viewer.stream("GET", f"/api/shifts/{sid}/stream?access_token={token}") as r:
        "".join(r.iter_text())
    after = alice.get(f"/api/shifts/{sid}", headers={"If-None-Match": before.headers["etag"]})
    assert after.status_code == 200 and "viewer@demo.local" in after.json()["viewers"]
    assert after.json()["version"] == before.json()["version"]


def test_unreported_tool_downs_stay_on_the_server():
    sid = _shift()
    view = alice.get(f"/api/shifts/{sid}").json()
    shown = {j["id"] for j in view["state"]["scenario"]["jobs"]}
    assert shown == set(view["state"]["released"])
    assert view["progress"]["total"] > len(shown)  # future tool-downs are counted, not shown
    later = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 600}).json()
    assert {j["id"] for j in later["state"]["scenario"]["jobs"]} == set(later["state"]["released"])
    assert len(later["state"]["released"]) > len(shown)


def test_ended_shifts_refuse_every_write():
    sid = _shift()
    end = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 24 * 60}).json()
    assert end["state"]["ended"] is True
    job = {"id": "LATE1", "x": 30, "y": 40, "skill": "etch", "earliest": 0, "latest": 60}
    for path, body in (
        ("advance", {"minutes": 10}),
        ("jobs", {"job": job}),
        ("engineers/E01/off", None),
        ("release", None),
    ):
        r = alice.post(f"/api/shifts/{sid}/{path}", json=body)
        assert r.status_code == 409 and "ended" in r.json()["error"]["message"], path
    assert alice.get(f"/api/shifts/{sid}").json()["version"] == end["version"]


def test_actions_that_change_nothing_keep_the_version():
    sid = _shift()
    v1 = alice.get(f"/api/shifts/{sid}").json()["version"]
    released = alice.post(f"/api/shifts/{sid}/release").json()  # alice doesn't hold the clock
    assert released["version"] == v1 and released["events"] == []
    off = alice.post(f"/api/shifts/{sid}/engineers/E01/off").json()
    assert off["version"] == v1 + 1
    again = alice.post(f"/api/shifts/{sid}/engineers/E01/off").json()
    assert again["version"] == v1 + 1 and again["events"] == []
    assert alice.get(f"/api/shifts/{sid}").json()["version"] == v1 + 1


def test_reported_jobs_are_checked_against_the_fab_and_the_size_cap():
    sid = _shift()
    job = {"id": "JX9", "x": 30, "y": 40, "skill": "no_such_family", "earliest": 0, "latest": 60}
    r = alice.post(f"/api/shifts/{sid}/jobs", json={"job": job})
    assert r.status_code == 422 and "no_such_family" in r.json()["error"]["message"]

    sc = alice.post("/api/scenario", json={"seed": 2, "n_engineers": 4, "n_jobs": 200}).json()
    full = alice.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]
    r = alice.post(f"/api/shifts/{full}/jobs", json={"job": {**job, "skill": "etch"}})
    assert r.status_code == 413
    assert alice.get(f"/api/shifts/{full}").json()["version"] == 1


def test_only_one_dispatcher_drives_the_clock():
    sid = _shift()
    bob = _other_dispatcher()
    assert alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}).status_code == 200
    r = bob.post(f"/api/shifts/{sid}/advance", json={"minutes": 10})
    assert r.status_code == 409 and "driving the clock" in r.json()["error"]["message"]
    assert alice.get(f"/api/shifts/{sid}").json()["clock_driver"] == "dispatcher@demo.local"
    alice.post(f"/api/shifts/{sid}/release")
    assert bob.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}).status_code == 200


def test_events_record_who_did_what():
    sid = _shift()
    alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 30})
    events = alice.get(f"/api/shifts/{sid}/events").json()
    assert {e["actor"] for e in events if e["kind"] in ("shift_started", "clock")} == {"dispatcher@demo.local"}


def test_stream_marks_viewers_present():
    sid = _shift()
    viewer = TestClient(app, headers=auth_headers("viewer"))
    token = issue_demo_token("viewer", get_settings())
    with viewer.stream("GET", f"/api/shifts/{sid}/stream?access_token={token}") as r:
        "".join(r.iter_text())
    assert "viewer@demo.local" in alice.get(f"/api/shifts/{sid}").json()["viewers"]


def test_shift_list_is_per_fab_with_summaries():
    sid = _shift()
    rows = alice.get("/api/shifts", params={"fab_id": "fab1-300mm-logic"}).json()
    row = next(r for r in rows if r["id"] == sid)
    assert row["created_by"] == "dispatcher@demo.local" and row["algorithm"] == "greedy"
    assert all(r["id"] != sid for r in alice.get("/api/shifts", params={"fab_id": "fab2-200mm-analog"}).json())


def test_retention_endpoint_requires_the_cron_secret(monkeypatch):
    assert alice.post("/api/internal/prune").status_code == 401
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret-value")
    assert alice.post("/api/internal/prune", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = alice.post("/api/internal/prune", headers={"Authorization": "Bearer s3cret-value"})
    assert r.status_code == 200 and "plan_cache" in r.json()["deleted"]


def test_migrations_upgrade_a_pre_versioning_database(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE shifts (id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at TEXT NOT NULL,
                             updated_at TEXT NOT NULL, state TEXT NOT NULL);
        INSERT INTO shifts VALUES ('old1', 3, '2026-01-01', '2026-01-01', '{"clock": 5}');""")
    legacy.commit()
    legacy.close()
    store = SQLiteStore(str(path))
    assert store.migrate() == list(range(1, SCHEMA_VERSION + 1))
    assert store.migrate() == []  # idempotent
    assert store.schema_version() == SCHEMA_VERSION
    assert store.get_shift("old1") == ({"clock": 5}, 3)
    assert store.list_shifts("fab1-300mm-logic")[0]["id"] == "old1"  # backfilled into the default fab


# ------------------------------------------------------------------ stream tickets
def _stream_text(client: TestClient, url: str) -> tuple[int, str]:
    with client.stream("GET", url) as r:
        return r.status_code, "".join(r.iter_text()) if r.status_code == 200 else ""


def test_a_stream_ticket_opens_the_stream_and_can_be_reused_within_its_lifetime():
    sid = _shift()
    viewer = TestClient(app, headers=auth_headers("viewer"))
    body = viewer.post(f"/api/shifts/{sid}/stream-ticket").json()
    assert body["expires_in"] == 90 and body["ticket"].count(".") == 1
    anon = TestClient(app)
    status, text = _stream_text(anon, f"/api/shifts/{sid}/stream?ticket={body['ticket']}")
    assert status == 200 and "retry:" in text
    assert _stream_text(anon, f"/api/shifts/{sid}/stream?ticket={body['ticket']}")[0] == 200  # a reconnect
    assert "viewer@demo.local" in alice.get(f"/api/shifts/{sid}").json()["viewers"]
    assert anon.get(f"/api/shifts/{sid}/stream").status_code == 401  # no ticket, no token
    assert anon.get(f"/api/shifts/{sid}").status_code == 401  # a ticket is not a session


def test_stream_tickets_are_bound_to_one_shift_expire_and_detect_tampering():
    from app.auth import User, issue_stream_ticket

    s = get_settings()
    sid, other = _shift(), _shift()
    user = User(id="demo-viewer", email="viewer@demo.local", role="viewer", fabs=["*"], provider="demo")
    anon = TestClient(app)
    for_other = issue_stream_ticket(user, other, s)
    r = anon.get(f"/api/shifts/{sid}/stream?ticket={for_other}")
    assert r.status_code == 401 and "another shift" in r.json()["error"]["message"]
    expired = issue_stream_ticket(user, sid, s, ttl_s=-1)
    r = anon.get(f"/api/shifts/{sid}/stream?ticket={expired}")
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]
    good = issue_stream_ticket(user, sid, s)
    body, sig = good.split(".")
    # A viewer promoting themselves to dispatcher in the payload breaks the signature.
    forged_body = body[:-2] + ("AA" if body[-2:] != "AA" else "BB")
    for bad in (f"{forged_body}.{sig}", f"{body}.{sig[:-3]}abc", body, "garbage", f"{body}.", "."):
        assert anon.get(f"/api/shifts/{sid}/stream?ticket={bad}").status_code == 401, bad
    # Signed with another key (another process without a shared secret): refused.
    from app.config import Settings

    foreign = issue_stream_ticket(user, sid, Settings(env="test", auth_secret="another-process-key-0123456789"))
    assert anon.get(f"/api/shifts/{sid}/stream?ticket={foreign}").status_code == 401


def test_a_ticket_needs_access_to_the_shift_and_the_token_fallback_warns(caplog):
    import logging

    sid = _shift()
    assert TestClient(app).post(f"/api/shifts/{sid}/stream-ticket").status_code == 401
    assert alice.post("/api/shifts/fab1-300mm-logic.nope/stream-ticket").status_code == 404
    token = issue_demo_token("viewer", get_settings())
    with caplog.at_level(logging.WARNING, logger="fab"):
        assert _stream_text(TestClient(app), f"/api/shifts/{sid}/stream?access_token={token}")[0] == 200
    assert any("deprecated" in r.message and "stream-ticket" in r.message for r in caplog.records)


def test_the_ticket_key_falls_back_to_a_per_process_secret_with_a_warning(caplog):
    import logging

    from app import auth
    from app.config import Settings

    demo = Settings(env="test")
    assert auth.stream_ticket_secret(demo) == demo.auth_secret.encode()  # demo sessions use the same key
    explicit = Settings(env="test", stream_ticket_secret="tickets-only-key")
    assert auth.stream_ticket_secret(explicit) == b"tickets-only-key"
    base = {"auth_mode": "supabase", "supabase_url": "https://abc.supabase.co"}
    with_jwt = Settings(**base, supabase_jwt_secret="shared-hs256-secret")
    assert auth.stream_ticket_secret(with_jwt) == b"shared-hs256-secret"
    auth._process_secret.cache_clear()
    with caplog.at_level(logging.WARNING, logger="fab"):
        key = auth.stream_ticket_secret(Settings(**base))  # asymmetric JWTs: no shared secret at all
        again = auth.stream_ticket_secret(Settings(**base))
    assert key == again and len(key) == 32
    assert sum("per-process key" in r.message for r in caplog.records) == 1  # warned once, not per ticket
