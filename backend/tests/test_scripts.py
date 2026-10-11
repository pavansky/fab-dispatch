"""The evidence base runs: every study script behind docs/ANALYSIS.md and the UI fixtures has a
smoke test that drives its real entry point at a tiny size.

The numbers in ANALYSIS.md come from these scripts, so they are covered like the app (CI measures
``--cov=scripts`` too). Each test runs the script's ``main`` in-process with the smallest sizes its
flags allow, checks the printed or returned tables have the expected keys, and, wherever a proven
optimum is produced, that no heuristic beats it. Each should finish in well under 20 s.
"""

import json

import pytest

from app.algorithms import ALGORITHMS

SOLVERS = set(ALGORITHMS)


def test_benchmark_prints_every_study_and_no_heuristic_beats_the_optimum(capsys):
    from scripts import benchmark

    results = benchmark.main(
        ["--seeds", "1", "--engineers", "4", "--jobs", "8", "--gap-seeds", "1", "--gap-size", "4x8"]
        + ["--scaling-sizes", "4x8", "--budget-seeds", "1"]
    )
    out = capsys.readouterr().out
    assert set(results) == {"quality", "gaps", "scaling", "budgets"}
    for heading in ("### Quality", "### Optimality gap", "### Solve time", "### Iteration budget"):
        assert heading in out
    metrics = {k for k, _ in benchmark.COLUMNS} | {"wins"}
    assert set(results["quality"]) == set(benchmark.PRESETS)
    for per_strategy in results["quality"].values():
        assert set(per_strategy) == SOLVERS
        assert all(set(row) == metrics for row in per_strategy.values())
    assert set(results["gaps"]) == SOLVERS
    for strategy, row in results["gaps"].items():
        assert set(row) == {"mean_gap_pct", "worst_gap_pct", "optimal_in"}
        assert row["mean_gap_pct"] >= -1e-6, f"{strategy} beat the proven optimum"
    assert set(results["scaling"]) == {"4x8"} and set(results["scaling"]["4x8"]) == SOLVERS
    assert [(r["solver"], r["iterations"]) for r in results["budgets"]] == [
        ("ALNS", 100),
        ("ALNS", 300),
        ("ALNS", 600),
        ("PyVRP", 250),
        ("PyVRP", 1000),
        ("PyVRP", 3000),
    ]
    assert all(set(r) == {"solver", "iterations", "cost_below_regret_pct", "mean_ms"} for r in results["budgets"])


def test_benchmark_full_size_gap_study_runs_per_preset(capsys):
    from scripts import benchmark

    results = benchmark.main(
        ["--only", "gaps-full", "--gap-seeds", "1", "--engineers", "4", "--jobs", "8", "--workers", "1"]
    )
    out = capsys.readouterr().out
    assert "### Optimality gap at full size" in out and "Exact solve (enumerate + MILP)" in out
    table = results["gaps_full"]
    assert set(table) == set(benchmark.PRESETS) | {"all"}
    for rows in table.values():
        assert set(rows) == SOLVERS
        for strategy, row in rows.items():
            assert set(row) == {"mean_gap_pct", "worst_gap_pct", "optimal_in"}
            assert row["mean_gap_pct"] >= -1e-6, f"{strategy} beat the proven optimum"


def test_scale_study_reports_the_company_live_events_and_single_problems(tmp_path):
    from scripts import scale_study

    out = tmp_path / "scale"
    report = scale_study.main(
        [str(out), "--areas", "2", "--area-size", "4x10", "--events", "3"] + ["--sizes", "4x10", "--workers", "1"]
    )
    assert set(report) == {"company", "live_events", "single_large"}
    company = report["company"]
    assert company["areas"] == 2 and company["engineers_on_shift"] == 8 and company["jobs"] == 20
    assert {"wall_s", "cpu_s", "per_area_p50_s", "per_area_p95_s", "coverage_mean_pct"} <= set(company)
    assert report["live_events"]["events"] == 3
    assert {"p50_s", "p95_s", "max_s"} <= set(report["live_events"])
    assert [(r["size"], r["algorithm"]) for r in report["single_large"]] == [
        ("4x10", "regret"),
        ("4x10", "alns"),
        ("4x10", "pyvrp"),
    ]
    assert json.loads(out.with_suffix(".json").read_text()) == report
    assert "done" in out.with_suffix(".log").read_text()


def test_certified_bound_brackets_the_optimum_and_restores_the_route_cap(tmp_path):
    from app.algorithms import exact
    from scripts import certified_bound

    cap = exact.MAX_ROUTES
    report = certified_bound.main(["4", "8", "0", str(tmp_path / "cg"), "--workers", "1"])
    assert exact.MAX_ROUTES == cap, "the script must not leave the app's route cap raised"
    assert report["size"] == "4x8" and report["routes"] > 0
    assert report["lower_bound"] <= report["best_plan"] + 1e-6
    assert report["best_plan_gap_to_bound_pct"] >= -1e-6
    assert set(report["heuristics"]) == SOLVERS
    for strategy, row in report["heuristics"].items():
        assert set(row) == {"cost", "seconds", "gap_to_best_pct", "max_gap_to_optimum_pct"}
        assert row["cost"] >= report["lower_bound"] - 1e-6, f"{strategy} beat the certified lower bound"
    assert json.loads((tmp_path / "cg.json").read_text()) == report


def test_duration_study_scores_every_estimator(tmp_path):
    from scripts import duration_study

    report = duration_study.main(
        [str(tmp_path / "dur"), "--fab", "fab1-300mm-logic", "--train-n", "300", "--test-n", "40"]
        + ["--gbm-iters", "20"]
    )
    assert [r["fab"] for r in report] == ["fab1-300mm-logic"]
    res = report[0]
    assert res["train"] == 300 and res["test"] == 40
    assert set(res["methods"]) == {"catalogue", "code_mean", "knn", "classifier", "gbm", "oracle_cause"}
    for name, m in res["methods"].items():
        assert {"mae_min", "overrun_pct"} <= set(m), name
        assert m["mae_min"] >= 0 and 0 <= m["overrun_pct"] <= 100
    assert {"chance", "ceiling", "knn", "classifier"} <= set(res["cause_recovery"])
    written = json.loads((tmp_path / "dur.json").read_text())
    assert written["fabs"] == report and written["quick"] is False


def test_predictive_study_compares_scenarios_against_reactive_dispatch(tmp_path):
    from scripts import predictive_study

    report = predictive_study.main(
        [str(tmp_path / "pred"), "--quick", "--shifts", "2", "--engineers", "6", "--jobs", "16", "--workers", "1"]
    )
    assert [r["scenario"] for r in report] == predictive_study.QUICK
    for row in report:
        assert {"recall", "precision", "lead_min", "unplanned_downtime_min", "tool_unavailable_min"} <= set(row)
        assert {"unplanned_saved_min", "unplanned_saved_ci95", "availability_gain_min"} <= set(row)
        assert 0 <= row["prevented_pct"] <= 100
    reactive = report[0]
    assert reactive["unplanned_saved_min"] == 0 and reactive["prevented_pct"] == 0
    written = json.loads((tmp_path / "pred.json").read_text())
    assert written["size"] == "6x16 normal" and written["shifts"] == 2


def test_learned_policy_study_scores_against_proven_optima(tmp_path):
    from scripts import learned_policy_study

    report = learned_policy_study.main(
        [str(tmp_path / "learned"), "--quick", "--engineers", "4", "--jobs", "10", "--workers", "1"]
    )
    assert report["size"] == "4x10" and report["cem"]["seeds"] == 1
    assert set(report["test"]) == set(learned_policy_study.SOLVERS) | {"hand_rule"}
    for strategy, row in report["test"].items():
        assert set(row) == {"mean_gap_pct", "worst_gap_pct"}
        assert row["mean_gap_pct"] >= -1e-6, f"{strategy} beat the proven optimum"
    assert len(report["learned_per_seed"]) == 1 and len(report["learned_per_seed"][0]["weights"]) == 6
    assert {"mean_gap_pct", "min_gap_pct", "max_gap_pct"} <= set(report["learned_across_seeds"])
    assert set(report["paired"]) == {"best_seed", "median_seed"}
    assert (tmp_path / "exact_optima.json").exists(), "optima are cached for re-runs"


def test_eval_report_prints_the_assistant_scorecard(capsys):
    from scripts import eval_report

    eval_report.main()
    out = capsys.readouterr().out
    assert out.startswith("## Assistant evaluation")
    for row in ("Right article cited (keyword phrasings)", "Off-topic questions declined", "Refusal threshold"):
        assert f"| {row} |" in out


def test_export_ui_fixtures_writes_every_fixture_and_the_export_note(tmp_path, monkeypatch):
    from scripts import export_ui_fixtures

    monkeypatch.setattr(export_ui_fixtures, "OUT", tmp_path)
    monkeypatch.setattr(export_ui_fixtures, "export", lambda: {"health": {"status": "ok"}, "shifts": []})
    export_ui_fixtures.main()
    assert json.loads((tmp_path / "health.json").read_text()) == {"status": "ok"}
    assert json.loads((tmp_path / "shifts.json").read_text()) == []
    note = json.loads((tmp_path / export_ui_fixtures.META_NOTE).read_text())
    assert note["export_budgets"] == {"alns_iterations": 60, "pyvrp_iterations": 300}
    assert note["shipped_budgets"] == {"alns_iterations": 300, "pyvrp_iterations": 1000}


@pytest.mark.parametrize(
    "script",
    ["benchmark", "scale_study", "certified_bound", "duration_study"] + ["predictive_study", "learned_policy_study"],
)
def test_every_script_documents_its_flags(script, capsys):
    import importlib

    module = importlib.import_module(f"scripts.{script}")
    with pytest.raises(SystemExit) as exit_info:
        module.main(["--help"])
    assert exit_info.value.code == 0
    assert "usage:" in capsys.readouterr().out
