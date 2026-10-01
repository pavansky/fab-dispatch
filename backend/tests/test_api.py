"""HTTP contract: caching headers, error envelope, planning endpoints and the live-shift flow."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def scenario():
    return client.post("/api/scenario", json={"seed": 1, "n_engineers": 6, "n_jobs": 18}).json()


def test_api_root_points_to_docs_and_ui():
    body = client.get("/").json()
    assert body["docs"] == "/docs" and "5173" in body["ui"]


def test_health_and_liveness():
    assert client.get("/api/livez").json() == {"status": "ok"}
    body = client.get("/api/health").json()
    assert body["db_ok"] is True and body["status"] == "ok"


def test_meta_is_cacheable_with_etag():
    r = client.get("/api/meta")
    assert set(r.json()["algorithms"]) == {"greedy", "hungarian", "regret", "alns", "pyvrp"}
    assert "public" in r.headers["cache-control"]
    again = client.get("/api/meta", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_responses_carry_request_id_and_security_headers():
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_plan_is_served_from_cache_second_time(scenario):
    body = {"scenario": scenario, "algorithm": "regret"}
    first = client.post("/api/plan", json=body)
    second = client.post("/api/plan", json=body)
    assert first.status_code == 200
    assert second.headers["x-cache"] in {"memory", "store"}
    assert first.json()["assignments"] == second.json()["assignments"]


def test_allocate_runs_every_strategy(scenario):
    res = client.post("/api/allocate", json={"scenario": scenario}).json()
    assert [r["algorithm"] for r in res] == ["greedy", "hungarian", "regret", "alns", "pyvrp"]
    for r in res:
        assert r["metrics"]["assigned"] + len(r["unassigned"]) == 18


def test_errors_use_one_envelope(scenario):
    r = client.post("/api/scenario", json={"preset": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid"
    r = client.post("/api/plan", json={"scenario": scenario, "algorithm": "magic"})
    assert r.status_code == 422 and "magic" in r.json()["error"]["message"]
    bad = json.loads(json.dumps(scenario))
    bad["jobs"][0]["latest"] = bad["jobs"][0]["earliest"] - 1
    r = client.post("/api/plan", json={"scenario": bad})
    assert r.status_code == 422 and r.json()["error"]["request_id"]
    assert client.get("/api/shifts/doesnotexist").json()["error"]["code"] == "not_found"


def test_benchmark_and_optimality_gap():
    body = client.post("/api/benchmark", json={"preset": "normal", "seeds": 2, "n_jobs": 10,
                                               "algorithms": ["greedy", "regret"]}).json()
    assert len(body["runs"]) == 4
    gap = client.post("/api/optimality-gap", json={"seeds": 1, "n_engineers": 3, "n_jobs": 8}).json()
    assert all(v >= -1e-6 for v in gap["mean_gap_pct"].values()), "a heuristic beat the proven optimum"


def test_live_shift_flow(scenario):
    created = client.post("/api/shifts", json={"scenario": scenario, "algorithm": "regret"}).json()
    sid, v1 = created["state"]["id"], created["version"]
    assert created["events"][0]["kind"] == "shift_started"

    adv = client.post(f"/api/shifts/{sid}/advance", json={"minutes": 120}).json()
    assert adv["version"] == v1 + 1 and adv["state"]["clock"] == 120

    # Stale If-Match is rejected rather than silently overwriting.
    stale = client.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}, headers={"If-Match": str(v1)})
    assert stale.status_code == 409

    eng = scenario["engineers"][0]["id"]
    off = client.post(f"/api/shifts/{sid}/engineers/{eng}/off").json()
    assert eng in off["state"]["off_shift"]

    job = {"id": "JX1", "x": 30, "y": 40, "skill": "etch", "earliest": 0, "latest": 60, "priority": 3}
    rep = client.post(f"/api/shifts/{sid}/jobs", json={"job": job}).json()
    assert "JX1" in rep["status"]

    events = client.get(f"/api/shifts/{sid}/events").json()
    kinds = [e["kind"] for e in events]
    assert {"shift_started", "replanned", "engineer_off", "job_reported", "clock"} <= set(kinds)
    assert events == sorted(events, key=lambda e: e["id"])

    later = client.get(f"/api/shifts/{sid}/events", params={"after": events[-2]["id"]}).json()
    assert len(later) == 1

    got = client.get(f"/api/shifts/{sid}")
    assert client.get(f"/api/shifts/{sid}", headers={"If-None-Match": got.headers["etag"]}).status_code == 304


def test_sse_stream_replays_events_after_cursor(scenario):
    sid = client.post("/api/shifts", json={"scenario": scenario, "algorithm": "greedy"}).json()["state"]["id"]
    with client.stream("GET", f"/api/shifts/{sid}/stream", headers={"Last-Event-ID": "0"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    assert "event: shift_started" in text and "event: replanned" in text
