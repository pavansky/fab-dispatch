"""Export real API responses as fixtures for the frontend component tests.

The UI tests render against these files instead of hand-written mocks, so they exercise
the exact shapes the API returns. ``tests/test_ui_fixtures.py`` fails when the API's
response shape drifts from the committed fixtures; re-run this script to refresh them:

    cd backend && python -m scripts.export_ui_fixtures
"""

from __future__ import annotations

import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"

# A small, crowded shift: every strategy leaves some work unserved, so the fixtures cover
# both explanations (assigned) and rejection reasons (unassigned).
SCENARIO = {"fab_id": "fab1-300mm-logic", "preset": "litho_crunch", "seed": 7, "n_engineers": 6, "n_jobs": 18}
BENCHMARK = {"fab_id": "fab1-300mm-logic", "preset": "normal", "seeds": 3, "n_engineers": 5, "n_jobs": 12}


def _setup_env() -> None:
    os.environ.setdefault("FAB_AUTH_MODE", "demo")
    os.environ.setdefault("FAB_DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("FAB_ALNS_ITERATIONS", "60")
    os.environ.setdefault("FAB_PYVRP_ITERATIONS", "300")


def export() -> dict[str, object]:
    """Call the API in-process and return {fixture name: response body}."""
    _setup_env()
    from fastapi.testclient import TestClient

    from app.algorithms import ALGORITHMS
    from app.auth import issue_demo_token
    from app.config import get_settings
    from app.help import load_articles
    from app.main import app

    token = issue_demo_token("dispatcher", get_settings())
    c = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def ok(r):
        assert r.status_code == 200, (r.request.url, r.status_code, r.text)
        return r.json()

    scenario = ok(c.post("/api/scenario", json=SCENARIO))
    meta = ok(c.get("/api/meta"))
    plans = {
        algo: ok(
            c.post("/api/plan", json={"scenario": scenario, "weights": meta["default_weights"], "algorithm": algo})
        )
        for algo in ALGORITHMS
    }
    shift = ok(
        c.post("/api/shifts", json={"scenario": scenario, "weights": meta["default_weights"], "algorithm": "alns"})
    )
    sid = shift["state"]["id"]
    advanced = ok(c.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}))
    events = ok(c.get(f"/api/shifts/{sid}/events"))
    recent = ok(c.get("/api/shifts", params={"fab_id": SCENARIO["fab_id"]}))
    ask = {
        "job": ok(
            c.post(
                "/api/assistant/ask",
                json={"question": "Why is J006 assigned this way?", "context": {"scenario": scenario}},
            )
        ),
        "docs": ok(c.post("/api/assistant/ask", json={"question": "How do I report a tool-down during a live shift?"})),
        "unknown": ok(c.post("/api/assistant/ask", json={"question": "Tell me a joke"})),
    }
    benchmark = ok(c.post("/api/benchmark", json=BENCHMARK))
    # Wall-clock times differ run to run; pin them so regenerating doesn't churn the diff.
    pinned = {"greedy": 2, "hungarian": 3, "regret": 6, "alns": 180, "pyvrp": 390}
    for p in plans.values():
        p["metrics"]["runtime_ms"] = pinned[p["algorithm"]]
        if "runtime_ms" in p["solver"]:
            p["solver"]["runtime_ms"] = pinned[p["algorithm"]]
    for run in benchmark["runs"]:
        run["metrics"]["runtime_ms"] = pinned[run["algorithm"]]
    return {
        "auth_config": ok(c.get("/api/auth/config")),
        "me": ok(c.get("/api/auth/me")),
        "meta": meta,
        "fabs": ok(c.get("/api/fabs")),
        "fab1": ok(c.get("/api/fabs/fab1-300mm-logic")),
        "fab2": ok(c.get("/api/fabs/fab2-200mm-analog")),
        "scenario": scenario,
        "scenario_fab2": ok(
            c.post("/api/scenario", json={**SCENARIO, "fab_id": "fab2-200mm-analog", "preset": "normal"})
        ),
        "plans": plans,
        "benchmark": benchmark,
        "shift": shift,
        "shift_advanced": advanced,
        "shift_events": events,
        "shifts": recent,
        "help_index": ok(c.get("/api/help")),
        "help_articles": {slug: ok(c.get(f"/api/help/{slug}")) for slug in load_articles()},
        "help_search": ok(c.get("/api/help/search", params={"q": "idle wait"})),
        # Every article's section anchors, so UI tests can check each in-app help link resolves.
        "help_anchors": {a.slug: [s.anchor for s in a.sections] for a in load_articles().values()},
        "ask_job": ask["job"],
        "ask_docs": ask["docs"],
        "ask_unknown": ask["unknown"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in export().items():
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=1) + "\n")
        print(f"wrote {OUT / name}.json")


if __name__ == "__main__":
    main()
