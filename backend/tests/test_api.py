"""HTTP contract: caching headers, error envelope, planning endpoints and the live-shift flow."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("dispatcher"))
anonymous = TestClient(app)


@pytest.fixture(scope="module")
def scenario():
    return client.post("/api/scenario", json={"seed": 1, "n_engineers": 6, "n_jobs": 18}).json()


def test_api_root_points_to_docs_and_ui():
    body = anonymous.get("/").json()
    assert body["docs"] == "/api/docs" and "5173" in body["ui"]


def test_api_reference_is_served_under_api_so_it_works_behind_the_vercel_rewrite():
    assert anonymous.get("/api/docs").status_code == 200
    assert anonymous.get("/api/redoc").status_code == 200
    spec = anonymous.get("/api/openapi.json").json()
    assert spec["info"]["version"] and "/api/assistant/ask" in spec["paths"]
    assert anonymous.get("/docs").status_code == 404  # the web app owns /docs in production


def test_health_and_liveness():
    assert anonymous.get("/api/livez").json() == {"status": "ok"}
    body = anonymous.get("/api/health").json()
    assert body["db_ok"] is True and body["schema_ok"] is True and body["status"] == "ok"


def test_meta_is_cacheable_with_etag():
    r = client.get("/api/meta")
    assert set(r.json()["algorithms"]) == {"greedy", "hungarian", "regret", "alns", "pyvrp"}
    assert "public" in r.headers["cache-control"]
    again = client.get("/api/meta", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_meta_reports_the_repair_index_actually_in_use():
    from app.deps import get_repairs

    assert anonymous.get("/api/meta").json()["vector_index"] == get_repairs().mode == "exact"


def test_health_checks_the_databases_at_most_once_per_interval(monkeypatch):
    from app.routes import system

    checks = []
    monkeypatch.setattr(system, "_health", {})
    monkeypatch.setattr(system, "_check_databases", lambda: checks.append(1) or (True, True, 1))
    for _ in range(5):
        assert anonymous.get("/api/health").json()["status"] == "ok"
    assert len(checks) == 1
    monkeypatch.setattr(system, "HEALTH_CACHE_S", 0.0)
    anonymous.get("/api/health")
    assert len(checks) == 2


def test_health_reports_a_database_that_is_down(monkeypatch):
    from app.routes import system

    class Down:
        kind = "postgres"

        def schema_version(self):
            raise ConnectionError("refused")

    monkeypatch.setattr(system, "_health", {})
    monkeypatch.setattr(system, "all_stores", lambda: [Down()])
    body = anonymous.get("/api/health").json()
    assert body["status"] == "degraded" and body["db_ok"] is False and body["databases"] == 1


def test_cache_stats_need_a_signed_in_user():
    assert anonymous.get("/api/cache/stats").status_code == 401
    assert set(client.get("/api/cache/stats").json()) == {"size", "hits", "misses"}


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
    assert anonymous.post("/api/scenario", json={}).json()["error"]["code"] == "unauthorised"
    r = client.post("/api/plan", json={"scenario": scenario, "algorithm": "magic"})
    assert r.status_code == 422 and "magic" in r.json()["error"]["message"]
    bad = json.loads(json.dumps(scenario))
    bad["jobs"][0]["latest"] = bad["jobs"][0]["earliest"] - 1
    r = client.post("/api/plan", json={"scenario": bad})
    assert r.status_code == 422 and r.json()["error"]["request_id"]
    assert client.get("/api/shifts/doesnotexist").json()["error"]["code"] == "not_found"


def test_benchmark_and_optimality_gap():
    body = client.post(
        "/api/benchmark", json={"preset": "normal", "seeds": 2, "n_jobs": 10, "algorithms": ["greedy", "regret"]}
    ).json()
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


def test_strategy_lists_are_bounded_and_deduplicated(scenario):
    r = client.post("/api/allocate", json={"scenario": scenario, "algorithms": ["greedy"] * 2000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid"
    res = client.post("/api/allocate", json={"scenario": scenario, "algorithms": ["regret", "greedy", "regret"]})
    assert [p["algorithm"] for p in res.json()] == ["regret", "greedy"]
    assert client.post("/api/allocate", json={"scenario": scenario, "algorithms": ["x" * 10_000]}).status_code == 422
    body = {"preset": "normal", "seeds": 1, "n_jobs": 5, "algorithms": ["greedy"] * 6}
    assert client.post("/api/benchmark", json=body).status_code == 422


def test_benchmark_work_is_capped_to_fit_the_serverless_time_limit():
    from app.routes.planning import BENCHMARK_MAX_JOB_RUNS

    r = client.post("/api/benchmark", json={"seeds": 30, "n_engineers": 60, "n_jobs": 120})
    assert r.status_code == 422 and "seeds x n_jobs" in r.json()["error"]["message"]
    assert 30 * 120 > BENCHMARK_MAX_JOB_RUNS >= 20 * 45  # the UI's largest default (20 seeds of 45 jobs) fits


def test_router_404_and_405_use_the_error_envelope():
    r = anonymous.get("/api/no-such-endpoint")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found" and "detail" not in r.json()
    r = anonymous.delete("/api/meta")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
    assert "GET" in r.headers["allow"]


def test_sse_cursor_is_validated_not_a_500(scenario):
    sid = client.post("/api/shifts", json={"scenario": scenario, "algorithm": "greedy"}).json()["state"]["id"]
    r = client.get(f"/api/shifts/{sid}/stream", params={"after": "abc"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid"
    assert client.get(f"/api/shifts/{sid}/stream", params={"after": -1}).status_code == 422
    # A malformed Last-Event-ID (here a superscript digit) falls back to ?after instead of failing.
    with client.stream("GET", f"/api/shifts/{sid}/stream", headers={"Last-Event-ID": b"\xb2"}) as r:
        assert r.status_code == 200
        assert "event: shift_started" in "".join(r.iter_text())


def test_unhandled_errors_still_carry_cors_headers(monkeypatch):
    from app.routes import fabs

    def boom():
        raise RuntimeError("bug")

    monkeypatch.setattr(fabs, "all_profiles", boom)
    r = client.get("/api/fabs", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers["x-request-id"]


# ------------------------------------------------------------------ security headers on the API
def test_every_api_response_carries_a_no_script_csp_and_the_docs_their_own():
    import base64
    import hashlib
    import re

    for path in ("/api/health", "/api/openapi.json", "/api/meta", "/api/nope"):
        r = anonymous.get(path)
        assert r.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'", path
        assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    for path in ("/api/docs", "/api/redoc"):
        r = anonymous.get(path)
        csp = r.headers["content-security-policy"]
        assert csp.startswith("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net")
        assert "'unsafe-inline'" not in csp.split("style-src")[0]  # scripts are never unsafe-inline
        assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
        assert "img-src 'self' data: https://fastapi.tiangolo.com" in csp and "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        # Every inline script on the page is pinned by hash, so the page works without unsafe-inline.
        for m in re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script[^>]*>", r.text, re.S | re.I):
            digest = base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode()
            assert f"'sha256-{digest}'" in csp
        # Everything the page loads is on the allow-list.
        for src in re.findall(r'(?:src|href)="(https://[^"]+)"', r.text):
            host = src.split("/")[2]
            assert host in ("cdn.jsdelivr.net", "fastapi.tiangolo.com", "fonts.googleapis.com"), src


def test_hsts_is_sent_in_production_or_over_https_and_not_on_a_plain_local_run():
    from fastapi import FastAPI

    from app.observability import HSTS, RequestContext

    assert "strict-transport-security" not in anonymous.get("/api/health").headers  # FAB_ENV=test, http
    plain, production = FastAPI(), FastAPI()
    for a in (plain, production):
        a.get("/x")(lambda: {"ok": True})
    plain.add_middleware(RequestContext)
    production.add_middleware(RequestContext, hsts=True)
    assert "strict-transport-security" not in TestClient(plain).get("/x").headers
    assert TestClient(plain, base_url="https://api.example").get("/x").headers["strict-transport-security"] == HSTS
    assert TestClient(production).get("/x").headers["strict-transport-security"] == HSTS
    assert HSTS.startswith("max-age=63072000")


def test_shift_size_limits_are_configurable(monkeypatch):
    """The 60 x 200 ceiling is a setting, not a constant: a local run raises it to plan 1000 x 1000,
    and every path that takes a size or a scenario (generate, plan, allocate, benchmark, live) uses it."""
    from app.config import get_settings

    c = TestClient(app, headers=auth_headers("dispatcher"))
    monkeypatch.setattr(get_settings(), "max_engineers", 5)
    monkeypatch.setattr(get_settings(), "max_jobs", 9)
    assert c.get("/api/meta").json()["limits"] == {"max_engineers": 5, "max_jobs": 9, "benchmark_max_job_runs": 1000}
    r = c.post("/api/scenario", json={"n_engineers": 6, "n_jobs": 9})
    assert r.status_code == 422 and "FAB_MAX_ENGINEERS" in r.text and "at most 5 engineers and 9 jobs" in r.text
    sc = c.post("/api/scenario", json={"n_engineers": 5, "n_jobs": 9}).json()
    assert c.post("/api/plan", json={"scenario": sc, "algorithm": "greedy"}).status_code == 200
    big = {**sc, "jobs": sc["jobs"] + [{**sc["jobs"][0], "id": "J999"}]}
    assert c.post("/api/plan", json={"scenario": big, "algorithm": "greedy"}).status_code == 422
    assert c.post("/api/allocate", json={"scenario": big, "algorithms": ["greedy"]}).status_code == 422
    assert c.post("/api/benchmark", json={"seeds": 1, "n_engineers": 5, "n_jobs": 10}).status_code == 422
    r = c.post("/api/shifts", json={"scenario": big, "algorithm": "greedy"})
    assert r.status_code == 413 and "FAB_MAX_ENGINEERS" in r.text  # scenario check, same limits
    monkeypatch.setattr(get_settings(), "max_engineers", 1000)
    monkeypatch.setattr(get_settings(), "max_jobs", 1000)
    r = c.post("/api/scenario", json={"n_engineers": 300, "n_jobs": 300})
    assert r.status_code == 200 and len(r.json()["jobs"]) == 300
