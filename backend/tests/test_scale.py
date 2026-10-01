"""System-design behaviours: the assignments read model, equipment-system ingestion, shared
rate limiting, and account deletion."""

import hashlib
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from tests.conftest import auth_headers

alice = TestClient(app, headers=auth_headers("dispatcher"))
FAB = "fab1-300mm-logic"
TOKEN = "test-ingest-token"


def _shift(seed: int = 9) -> str:
    sc = alice.post("/api/scenario", json={"seed": seed, "n_engineers": 6, "n_jobs": 16}).json()
    return alice.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]


def _tool_down(job_id: str, **extra) -> dict:
    return {
        "fab_id": FAB,
        "job": {
            "id": job_id,
            "x": 40,
            "y": 30,
            "skill": "etch",
            "priority": 3,
            "earliest": 0,
            "latest": 60,
            "duration": 45,
            "tool": "ETCH-07",
            "symptom": "RF reflected power high",
        },
        **extra,
    }


# ------------------------------------------------------------------ assignments read model
def test_read_model_tracks_every_write():
    sid = _shift()
    view = alice.get(f"/api/shifts/{sid}").json()
    rows = alice.get(f"/api/shifts/{sid}/assignments").json()
    assert {r["job_id"]: r["status"] for r in rows} == view["status"]
    after = alice.post(f"/api/shifts/{sid}/advance", json={"minutes": 120}).json()
    rows = alice.get(f"/api/shifts/{sid}/assignments").json()
    assert {r["job_id"]: r["status"] for r in rows} == after["status"]
    planned = {a["job_id"]: a["tech_id"] for a in after["state"]["plan"]["assignments"]}
    assert {r["job_id"]: r["engineer_id"] for r in rows if r["engineer_id"]} == planned


def test_engineer_history_is_a_query_not_a_document_scan():
    sid = _shift(seed=11)
    rows = alice.get(f"/api/shifts/{sid}/assignments").json()
    engineer = next(r["engineer_id"] for r in rows if r["engineer_id"])
    history = alice.get(f"/api/fabs/{FAB}/engineers/{engineer}/assignments").json()
    mine = {r["job_id"] for r in rows if r["engineer_id"] == engineer}
    assert mine <= {h["job_id"] for h in history if h["shift_id"] == sid}


# ------------------------------------------------------------------ ingestion
@pytest.fixture
def ingest_token(monkeypatch):
    monkeypatch.setitem(get_settings().ingest_tokens, FAB, hashlib.sha256(TOKEN.encode()).hexdigest())
    return {"Authorization": f"Bearer {TOKEN}"}


def test_equipment_systems_report_tool_downs_into_the_live_shift(ingest_token):
    sid = _shift(seed=12)
    job_id = f"MES-{uuid.uuid4().hex[:6]}"
    r = TestClient(app).post(
        "/api/ingest/tool-downs",
        json=_tool_down(job_id, shift_id=sid),
        headers={**ingest_token, "Idempotency-Key": job_id},
    )
    assert r.status_code == 202, r.text
    assert r.json()["shift_id"] == sid and r.json()["status"] in ("planned", "in_progress", "unassigned")
    events = alice.get(f"/api/shifts/{sid}/events").json()
    reported = [e for e in events if e["kind"] == "job_reported"]
    assert reported[-1]["data"]["job_id"] == job_id and reported[-1]["actor"] == f"integration ({FAB})"


def test_a_retried_message_reports_the_fault_once(ingest_token):
    sid = _shift(seed=13)
    job_id = f"MES-{uuid.uuid4().hex[:6]}"
    body, headers = _tool_down(job_id, shift_id=sid), {**ingest_token, "Idempotency-Key": f"msg-{job_id}"}
    first = TestClient(app).post("/api/ingest/tool-downs", json=body, headers=headers).json()
    again = TestClient(app).post("/api/ingest/tool-downs", json=body, headers=headers).json()
    assert again["idempotent_replay"] is True and again["version"] == first["version"]
    jobs = alice.get(f"/api/shifts/{sid}").json()["state"]["scenario"]["jobs"]
    assert sum(j["id"] == job_id for j in jobs) == 1


def test_ingestion_needs_the_fabs_own_token(ingest_token):
    client = TestClient(app)
    body = _tool_down("MES-X")
    assert client.post("/api/ingest/tool-downs", json=body, headers={"Idempotency-Key": "a"}).status_code == 401
    wrong = {"Authorization": "Bearer nope", "Idempotency-Key": "b"}
    assert client.post("/api/ingest/tool-downs", json=body, headers=wrong).status_code == 401
    other_fab = {**body, "fab_id": "fab2-200mm-specialty"}
    assert (
        client.post(
            "/api/ingest/tool-downs", json=other_fab, headers={**ingest_token, "Idempotency-Key": "c"}
        ).status_code
        == 401
    )
    # A user's session token is not an ingestion token either.
    assert (
        client.post("/api/ingest/tool-downs", json=body, headers={**auth_headers(), "Idempotency-Key": "d"}).status_code
        == 401
    )


def test_ingestion_requires_an_idempotency_key(ingest_token):
    r = TestClient(app).post("/api/ingest/tool-downs", json=_tool_down("MES-Y"), headers=ingest_token)
    assert r.status_code == 422


def test_ingestion_rejects_a_family_the_fab_does_not_have(ingest_token):
    body = _tool_down("MES-Z")
    body["job"]["skill"] = "nonexistent"
    r = TestClient(app).post("/api/ingest/tool-downs", json=body, headers={**ingest_token, "Idempotency-Key": "z"})
    assert r.status_code == 422


# ------------------------------------------------------------------ shared rate limiting
def test_the_quota_is_shared_across_instances(monkeypatch):
    """Two instances (two in-memory limiters) share one per-minute quota through the store."""
    from types import SimpleNamespace

    from app import deps
    from app.observability import RateLimiter

    monkeypatch.setattr(deps, "get_settings", lambda: Settings(env="local"))
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=f"u-{uuid.uuid4().hex[:6]}")), headers={})
    dep = deps.rate_limit("quota-test", per_min=3, burst=2)
    allowed = 0
    for i in range(10):
        monkeypatch.setattr(deps, "_limiter", RateLimiter())  # a fresh instance every request
        try:
            dep(request)
            allowed += 1
        except HTTPException as e:
            assert e.status_code == 429 and i >= 5
    assert allowed == 5  # per_min + burst, however many instances served it


def test_rate_limiting_fails_open_when_the_store_is_down(monkeypatch):
    from types import SimpleNamespace

    from app import deps

    class Down:
        def hit_rate(self, *a):
            raise ConnectionError("db down")

    monkeypatch.setattr(deps, "get_settings", lambda: Settings(env="local"))
    monkeypatch.setattr(deps, "get_store", lambda: Down())
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="u-down")), headers={})
    deps.rate_limit("down-test", per_min=60, burst=10)(request)  # no exception


# ------------------------------------------------------------------ account deletion
def test_deleting_your_account_erases_your_data_and_keeps_the_audit_trail():
    import jwt

    s = get_settings()
    from app.auth import issue_demo_token

    claims = jwt.decode(issue_demo_token("dispatcher", s), s.auth_secret, algorithms=["HS256"], audience="fab-dispatch")
    claims |= {"sub": "demo-leaver", "email": "leaver@demo.local"}
    leaver = TestClient(app, headers={"Authorization": f"Bearer {jwt.encode(claims, s.auth_secret)}"})
    sc = leaver.post("/api/scenario", json={"seed": 21, "n_engineers": 5, "n_jobs": 12}).json()
    sid = leaver.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]
    leaver.post(f"/api/shifts/{sid}/advance", json={"minutes": 30}, headers={"Idempotency-Key": "leave-1"})
    leaver.post("/api/assistant/feedback", json={"question": "q", "intent": "docs", "helpful": True})

    r = leaver.delete("/api/auth/me")
    assert r.status_code == 200
    erased = r.json()["erased"]
    assert erased["assistant_feedback"] == 1 and erased["shifts"] == 1 and erased["shift_events"] >= 2
    assert r.json()["account_deleted"] is False  # demo accounts are shared; only data is erased

    events = alice.get(f"/api/shifts/{sid}/events").json()
    assert events and all("leaver@demo.local" not in str(e) for e in events)
    assert all(e["actor"] != "leaver@demo.local" for e in events)
    shift = alice.get(f"/api/shifts/{sid}").json()["state"]
    assert shift["created_by"] == "a deleted user"
