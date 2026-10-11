"""The search solvers at the budgets the app ships with.

Every other automated layer (tests/conftest.py, the UI fixtures, Playwright) runs ALNS and PyVRP
at a fraction of the shipped iteration budgets so suites stay fast. This test runs them at the
budgets a user gets (the defaults in app/config.py, read from the model, not from the test
environment) on one full-size shift: the plans must still respect every hard constraint, be
identical across two runs (the iteration budget, not the wall clock, is the stop), and cost no
more than the quarter-budget plan does, since both searches keep their best plan.
"""

import time

import pytest

from app.algorithms import ALGORITHMS
from app.algorithms.alns import run_alns
from app.algorithms.pyvrp_ils import run_pyvrp
from app.config import Settings
from app.engine import allocate
from app.generator import generate
from app.models import Weights
from tests.test_constraints import assert_hard_constraints

SHIPPED = {name: Settings.model_fields[name].default for name in ("alns_iterations", "pyvrp_iterations")}
SHIPPED_CAP_S = Settings.model_fields["solver_time_limit_s"].default
# The shipped time cap is a safety net, not the budget: a generous one here keeps the stop
# deterministic on a slow runner; how long the solve took is printed next to the cap.
GENEROUS_CAP_S = 120.0
RUNNERS = {
    "alns": lambda p: run_alns(p, runtime_s=GENEROUS_CAP_S, max_iterations=SHIPPED["alns_iterations"]),
    "pyvrp": lambda p: run_pyvrp(p, runtime_s=GENEROUS_CAP_S, max_iterations=SHIPPED["pyvrp_iterations"]),
}


@pytest.mark.slow
@pytest.mark.parametrize("solver", sorted(RUNNERS))
def test_shipped_budget_plans_are_feasible_deterministic_and_no_worse_than_the_test_budget(solver, monkeypatch):
    assert SHIPPED == {"alns_iterations": 300, "pyvrp_iterations": 1000}, "ANALYSIS.md documents these budgets"
    sc = generate(0, 14, 45, "normal")
    quarter = allocate(sc, Weights(), solver)  # conftest's reduced budget, as every other suite runs
    monkeypatch.setitem(ALGORITHMS, f"{solver}@shipped", (f"{solver} at the shipped budget", RUNNERS[solver]))
    t0 = time.perf_counter()
    first = allocate(sc, Weights(), f"{solver}@shipped")
    elapsed = time.perf_counter() - t0
    second = allocate(sc, Weights(), f"{solver}@shipped")
    print(f"{solver} at {SHIPPED}: {elapsed:.2f} s on this machine (shipped safety cap {SHIPPED_CAP_S} s)")

    assert_hard_constraints(sc, first)
    assert [a.model_dump() for a in first.assignments] == [a.model_dump() for a in second.assignments]
    assert first.metrics["objective"] == pytest.approx(second.metrics["objective"])
    assert not first.solver.get("hit_time_cap"), "the iteration budget, not the clock, must be the stop"
    assert first.metrics["objective"] <= quarter.metrics["objective"] + 1e-6, (
        f"{solver} at the shipped budget ({first.metrics['objective']:.2f}) is worse than at the test "
        f"budget ({quarter.metrics['objective']:.2f}); the search no longer keeps its best plan"
    )
