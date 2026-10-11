"""Behavioural tests: hand-built cases where the algorithms *should* differ."""

import statistics

import pytest

from app.engine import allocate
from app.generator import generate
from app.models import Engineer, Job, Scenario, Weights
from app.planner import Planner


def test_greedy_falls_into_the_trap(greedy_trap):
    res = allocate(greedy_trap, Weights(), "greedy")
    assert {a.job_id: a.tech_id for a in res.assignments} == {"J1": "E-A"}
    assert [u.job_id for u in res.unassigned] == ["J2"]
    # Nobody is at max jobs: the reason given is the real one, the time window.
    reason = res.unassigned[0].reason
    assert "2 qualified engineer(s), but none can fit it in: 2 cannot arrive inside the time window" in reason
    assert "capacity" not in reason and "max jobs" not in reason


def test_hungarian_sees_the_global_picture(greedy_trap):
    res = allocate(greedy_trap, Weights(), "hungarian")
    assert {a.job_id: a.tech_id for a in res.assignments} == {"J1": "E-B", "J2": "E-A"}
    j1 = next(a for a in res.assignments if a.job_id == "J1")
    assert "globally optimal" in j1.explanation


def test_regret_places_the_constrained_job_first(greedy_trap):
    res = allocate(greedy_trap, Weights(), "regret")
    assert {a.job_id: a.tech_id for a in res.assignments} == {"J1": "E-B", "J2": "E-A"}
    j2 = next(a for a in res.assignments if a.job_id == "J2")
    assert "only one engineer" in j2.explanation


def test_unassigned_reason_names_capacity_only_when_it_is_the_cause():
    sc = Scenario(
        engineers=[Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 2}, max_jobs=1)],
        jobs=[
            Job(id="J1", x=10, y=0, skill="etch", priority=3, earliest=0, latest=100, duration=30),
            Job(id="J2", x=20, y=0, skill="etch", priority=2, earliest=0, latest=300, duration=30),
        ],
    )
    res = allocate(sc, Weights(), "greedy")
    assert [u.job_id for u in res.unassigned] == ["J2"]
    assert "none can fit it in: 1 already at max jobs" in res.unassigned[0].reason


@pytest.mark.parametrize("algorithm", ["greedy", "hungarian", "regret", "alns", "pyvrp"])
def test_a_job_that_costs_more_than_it_earns_is_left_out(algorithm):
    """Far: a PM (reward 60) 1.95 km past the other job, so the walk alone costs 78 points.
    Serving it makes the plan worse, so no method commits it, and the reason says why."""
    sc = Scenario(
        engineers=[Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 2})],
        jobs=[
            Job(id="Near", x=50, y=0, skill="etch", priority=2, earliest=0, latest=100, duration=30),
            Job(id="Far", x=2000, y=0, skill="etch", priority=1, kind="pm", earliest=0, latest=400, duration=30),
        ],
    )
    res = allocate(sc, Weights(), algorithm)
    assert [a.job_id for a in res.assignments] == ["Near"]
    assert [u.job_id for u in res.unassigned] == ["Far"]
    assert "leaving it out is cheaper" in res.unassigned[0].reason


def test_uncertified_family_is_reported_not_assigned():
    sc = Scenario(
        engineers=[Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 3})],
        jobs=[Job(id="J1", x=10, y=0, skill="litho", earliest=0, latest=100)],
    )
    for algo in ("greedy", "hungarian", "regret"):
        res = allocate(sc, Weights(), algo)
        assert not res.assignments
        assert "certified on litho" in res.unassigned[0].reason


def test_level_requirement_respected():
    sc = Scenario(
        engineers=[
            Engineer(id="Junior", name="a", x=0, y=0, skills={"litho": 1}),
            Engineer(id="Senior", name="b", x=900, y=0, skills={"litho": 3}),
        ],
        jobs=[Job(id="J1", x=5, y=0, skill="litho", min_level=3, earliest=0, latest=100)],
    )
    for algo in ("greedy", "hungarian", "regret"):
        assert allocate(sc, Weights(), algo).assignments[0].tech_id == "Senior"


def test_overqualification_penalty_saves_the_expert():
    """Same distance, so the level-1 engineer should take the level-1 job."""
    sc = Scenario(
        engineers=[
            Engineer(id="Expert", name="a", x=0, y=0, skills={"cmp": 3}),
            Engineer(id="Generalist", name="b", x=20, y=0, skills={"cmp": 1}),
        ],
        jobs=[Job(id="J1", x=10, y=0, skill="cmp", min_level=1, earliest=0, latest=100)],
    )
    assert allocate(sc, Weights(), "greedy").assignments[0].tech_id == "Generalist"
    no_penalty = Weights(overqualification=0)
    assert allocate(sc, no_penalty, "greedy").assignments[0].tech_id in {"Expert", "Generalist"}


def test_insertion_reorders_route_by_time():
    """A job added later but due earlier is inserted in front, not appended."""
    sc = Scenario(
        engineers=[Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 2})],
        jobs=[
            Job(id="Late", x=50, y=0, skill="etch", priority=3, earliest=200, latest=300, duration=30),
            Job(id="Early", x=60, y=0, skill="etch", priority=1, earliest=0, latest=60, duration=30),
        ],
    )
    res = allocate(sc, Weights(), "greedy")
    assert [s.job_id for s in res.routes[0].stops] == ["Early", "Late"]


def test_insertion_cost_is_the_exact_total_cost_change():
    """The cost an algorithm compares is exactly what the objective moves by (no per-term
    rounding), so ranking insertions and ranking plans agree."""
    sc = generate(seed=5, n_engineers=8, n_jobs=24)
    p = Planner(sc, Weights(travel_100m=3.337, wait_min=0.2371, overqualification=7.77))
    committed = 0
    for job_id in p.unplaced():
        feasible, _ = p.scan(job_id)
        if feasible:
            before = p.total_cost()
            p.commit(feasible[0])
            assert p.total_cost() - before == pytest.approx(feasible[0].cost, abs=1e-9)
            committed += 1
    assert committed > 10


@pytest.mark.parametrize("algorithm", ["greedy", "hungarian", "regret", "alns", "pyvrp"])
def test_reported_objective_is_the_cost_the_solvers_minimise(algorithm):
    """The 'objective' metric is Planner.total_cost of the returned plan (workload term
    included), and its parts add up to it."""
    sc = generate(seed=7, n_engineers=10, n_jobs=30)
    res = allocate(sc, Weights(), algorithm)
    replay = Planner(sc, Weights())
    for route in res.routes:
        for stop in route.stops:
            assert replay.append(route.tech_id, stop.job_id) is not None
    m = res.metrics
    assert m["objective"] == pytest.approx(replay.total_cost(), abs=0.051)
    assert m["workload_cost"] > 0
    parts = m["operating_cost"] + m["workload_cost"] + m["reassignment_cost"]
    assert m["objective"] == pytest.approx(parts, abs=0.16)


def test_batch_and_regret_serve_at_least_as_much_priority_on_average():
    """Across many seeds, smarter ordering should never lose priority-weighted coverage on average."""
    scores = {a: [] for a in ("greedy", "hungarian", "regret")}
    for preset in ("normal", "excursion", "litho_crunch"):
        for seed in range(12):
            sc = generate(seed=seed, n_engineers=12, n_jobs=45, preset=preset)
            for a in scores:
                scores[a].append(allocate(sc, Weights(), a).metrics["priority_weighted_coverage_pct"])
    mean = {a: statistics.fmean(v) for a, v in scores.items()}
    assert mean["hungarian"] >= mean["greedy"] - 0.5
    assert mean["regret"] >= mean["greedy"] - 0.5


def test_the_exact_optimum_is_proven_at_full_shift_size():
    """A full 14 x 45 shift is solved to proven optimality, and no heuristic beats it."""
    from app.algorithms import ALGORITHMS
    from app.algorithms.exact import run_exact
    from app.generator import generate
    from app.models import Weights
    from app.planner import Planner

    sc = generate(0, 14, 45, "normal")
    p = Planner(sc, Weights())
    run_exact(p)
    opt = p.total_cost()
    assert p.meta["solver"]["columns"] > 10_000
    for name, (_, fn) in ALGORITHMS.items():
        q = Planner(sc, Weights())
        fn(q)
        assert q.total_cost() >= opt - 1e-6, name
