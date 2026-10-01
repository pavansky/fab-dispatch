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
    assert store.migrate() == [1, 2]
    assert store.migrate() == []  # idempotent
    assert store.schema_version() == SCHEMA_VERSION
    assert store.get_shift("old1") == ({"clock": 5}, 3)
    assert store.list_shifts("fab1-300mm-logic")[0]["id"] == "old1"  # backfilled into the default fab
