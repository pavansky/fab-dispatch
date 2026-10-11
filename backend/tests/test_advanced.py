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
    for name, fn in [
        ("exact", run_exact),
        ("alns", lambda p: run_alns(p, seed=seed, max_iterations=300)),
        ("pyvrp", lambda p: run_pyvrp(p, seed=seed, max_iterations=2000)),
    ]:
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


def _live_instance(seed: int, clock: float = 180.0):
    """A re-plan at ``clock``: started stops frozen at their real times, previous owners known."""
    sc = generate(seed, 6, 18, "normal")
    base = allocate(sc, Weights(), "regret")
    frozen = {}
    for r in base.routes:
        started = [s for s in r.stops if s.start <= clock]
        frozen[r.tech_id] = Frozen(
            route=[s.job_id for s in started],
            not_before=clock,
            starts=[s.start for s in started],
            arrivals=[s.arrival for s in started],
        )
    return sc, frozen, {a.job_id: a.tech_id for a in base.assignments}


@pytest.mark.parametrize("seed", [0, 2, 3])
def test_exact_is_a_lower_bound_in_live_mode(seed):
    """Frozen work and the stability term are priced the same way as in total_cost, so
    the proven optimum is never beaten by a heuristic on a live re-plan either."""
    from app.algorithms import ALGORITHMS

    sc, frozen, owner = _live_instance(seed)
    p = Planner(sc, Weights(), frozen=frozen, previous_owner=owner)
    run_exact(p)
    opt = p.total_cost()
    assert any(frozen[t].route for t in frozen) and any(p.routes[t][len(frozen[t].route) :] for t in frozen)
    for name, (_, fn) in ALGORITHMS.items():
        q = Planner(sc, Weights(), frozen=frozen, previous_owner=owner)
        fn(q)
        assert q.total_cost() >= opt - 1e-6, f"{name} beat the proven optimum on a live re-plan"


def test_live_replan_does_not_rewrite_started_work():
    """A job started after an earlier re-plan keeps the times it really ran at (that
    re-plan's "not before now" delay included), so later re-plans can't move it earlier
    and double-book its engineer."""
    from app import live
    from app.models import Engineer, Job, Scenario

    pm = {"skill": "etch", "kind": "pm", "priority": 1, "earliest": 0, "latest": 600}
    sc = Scenario(
        engineers=[
            Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 2}),
            Engineer(id="E2", name="b", x=300, y=0, skills={"etch": 2}),
        ],
        jobs=[
            Job(id="A", x=300, y=0, duration=120, **pm),
            Job(id="C", x=300, y=0, duration=100, **pm),
            Job(id="B", x=0, y=0, duration=40, **pm),
        ],
    )
    state, _ = live.start(sc, Weights(), "regret")
    live.advance(state, 50)
    live.engineer_off(state, "E2")  # A moves to E1, who can't leave B's bay before 50
    a = next(s for r in state.plan.routes for s in r.stops if s.job_id == "A")
    assert (a.arrival, a.start, a.end) == (55.0, 55.0, 175.0)
    live.advance(state, 150)
    live.report_job(state, Job(id="D", x=300, y=0, skill="etch", priority=3, earliest=0, latest=60, duration=30))

    stops = {s.job_id: s for r in state.plan.routes for s in r.stops}
    assert stops["A"].locked and (stops["A"].arrival, stops["A"].start, stops["A"].end) == (55.0, 55.0, 175.0)
    for route in state.plan.routes:
        for prev, nxt in zip(route.stops, route.stops[1:], strict=False):
            assert nxt.start >= prev.end, f"{route.tech_id} double-booked: {prev.job_id} and {nxt.job_id}"
