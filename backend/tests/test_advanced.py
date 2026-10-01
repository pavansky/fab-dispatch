"""PyVRP, ALNS and the exact MILP: hard constraints, optimality ordering, live-mode freezing."""
import pytest

from app.algorithms.alns import run_alns
from app.algorithms.exact import run_exact
from app.algorithms.pyvrp_ils import run_pyvrp
from app.engine import allocate
from app.generator import generate
from app.models import Weights
from app.planner import Frozen, Planner

SEARCH = ["alns", "pyvrp"]


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("preset", ["normal", "litho_crunch", "excursion"])
def test_search_methods_never_lose_to_their_start(preset, seed):
    """ALNS and PyVRP both start from regret-2, so they must never end up worse."""
    sc = generate(seed, 12, 40, preset)
    regret = allocate(sc, Weights(), "regret").metrics
    for algo in SEARCH:
        p = Planner(sc, Weights())
        fn = run_alns if algo == "alns" else run_pyvrp
        fn(p, seed=seed)
        q = Planner(sc, Weights())
        from app.algorithms.regret import run_regret
        run_regret(q)
        assert p.total_cost() <= q.total_cost() + 1e-6, algo
    assert regret["assigned"] >= 0


@pytest.mark.parametrize("seed", range(5))
def test_exact_is_a_lower_bound_and_search_is_close(seed):
    sc = generate(seed, n_engineers=4, n_jobs=12, preset="normal")
    costs = {}
    for name, fn in [("exact", run_exact), ("alns", lambda p: run_alns(p, seed=seed, max_iterations=300)),
                     ("pyvrp", lambda p: run_pyvrp(p, seed=seed, max_iterations=2000))]:
        p = Planner(sc, Weights())
        fn(p)
        costs[name] = p.total_cost()
    for name in ("alns", "pyvrp"):
        assert costs[name] >= costs["exact"] - 1e-6, f"{name} beat the proven optimum: the model is inconsistent"
        assert costs[name] <= costs["exact"] * 1.10 + 1, f"{name} is >10% from optimal on a tiny instance"


def test_frozen_work_is_kept_in_place_by_every_method():
    sc = generate(3, 10, 30, "normal")
    base = allocate(sc, Weights(), "regret")
    # Freeze each engineer's first stop as if the clock were at 90 minutes.
    frozen = {r.tech_id: Frozen(route=[r.stops[0].job_id], not_before=90.0) for r in base.routes if r.stops}
    for algo in ["greedy", "hungarian", "regret", "alns", "pyvrp"]:
        res = allocate(sc, Weights(), algo, frozen=frozen)
        for r in res.routes:
            if r.tech_id in frozen:
                assert r.stops[0].job_id == frozen[r.tech_id].route[0], algo
                assert r.stops[0].locked
                for s in r.stops[1:]:
                    assert s.start >= 90.0 - 1e-6, f"{algo} scheduled open work in the past"
