"""Export real API responses as fixtures for the frontend component tests.

The UI tests render against these files instead of hand-written mocks, so they exercise
the exact shapes the API returns. ``tests/test_ui_fixtures.py`` fails when the API's
response shape drifts from the committed fixtures; re-run this script to refresh them:

    cd backend && python -m scripts.export_ui_fixtures
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"
# Written next to the fixtures (an underscore so the fixture contract test skips it): how they
# were produced, so a reader knows the timings are not the shipped app's.
META_NOTE = "_export_meta.json"

# The search solvers run at a fraction of the shipped iteration budgets (app/config.py: 300 ALNS,
# 1000 PyVRP) so regenerating is quick. Costs are therefore slightly worse than the live app's, and
# every runtime_ms is the export machine's measured wall clock, not a representative latency.
EXPORT_BUDGETS = {"FAB_ALNS_ITERATIONS": "60", "FAB_PYVRP_ITERATIONS": "300"}

# A small, crowded shift: every strategy leaves some work unserved, so the fixtures cover
# both explanations (assigned) and rejection reasons (unassigned).
SCENARIO = {"fab_id": "fab1-300mm-logic", "preset": "litho_crunch", "seed": 7, "n_engineers": 6, "n_jobs": 18}
BENCHMARK = {"fab_id": "fab1-300mm-logic", "preset": "normal", "seeds": 3, "n_engineers": 5, "n_jobs": 12}


def _setup_env() -> None:
    os.environ.setdefault("FAB_AUTH_MODE", "demo")
    os.environ.setdefault("FAB_DATABASE_URL", "sqlite:///:memory:")
    for key, value in EXPORT_BUDGETS.items():
        os.environ.setdefault(key, value)


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
    # runtime_ms stays as measured (it differs run to run); META_NOTE says where it was measured.
    benchmark = ok(c.post("/api/benchmark", json=BENCHMARK))
    return {
        "auth_config": ok(c.get("/api/auth/config")),
        "health": ok(c.get("/api/health")),
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


def export_note() -> dict[str, object]:
    """What the fixtures were produced with: reduced solver budgets, and timings from this machine."""
    from app.config import Settings

    shipped = {k: Settings.model_fields[k].default for k in ("alns_iterations", "pyvrp_iterations")}
    return {
        "note": (
            "Fixtures exported from the in-process API with reduced search budgets so regeneration is quick. "
            "Costs can be slightly worse than the live app's, and every runtime_ms is the wall clock measured "
            "on the export machine (below), not a representative latency."
        ),
        "export_budgets": {k.removeprefix("FAB_").lower(): int(v) for k, v in EXPORT_BUDGETS.items()},
        "shipped_budgets": shipped,
        "exported_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "machine": {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine()},
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in export().items():
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=1) + "\n")
        print(f"wrote {OUT / name}.json")
    (OUT / META_NOTE).write_text(json.dumps(export_note(), indent=1) + "\n")
    print(f"wrote {OUT / META_NOTE}")


if __name__ == "__main__":
    main()
