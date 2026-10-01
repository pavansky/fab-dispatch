"""Behavioural tests: hand-built cases where the algorithms *should* differ."""
import statistics

from app.engine import allocate
from app.generator import generate
from app.models import Engineer, Job, Scenario, Weights


def test_greedy_falls_into_the_trap(greedy_trap):
    res = allocate(greedy_trap, Weights(), "greedy")
    assert {a.job_id: a.tech_id for a in res.assignments} == {"J1": "E-A"}
    assert [u.job_id for u in res.unassigned] == ["J2"]
    assert "none had capacity" in res.unassigned[0].reason


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
        engineers=[Engineer(id="Junior", name="a", x=0, y=0, skills={"litho": 1}),
                   Engineer(id="Senior", name="b", x=900, y=0, skills={"litho": 3})],
        jobs=[Job(id="J1", x=5, y=0, skill="litho", min_level=3, earliest=0, latest=100)],
    )
    for algo in ("greedy", "hungarian", "regret"):
        assert allocate(sc, Weights(), algo).assignments[0].tech_id == "Senior"


def test_overqualification_penalty_saves_the_expert():
    """Same distance, so the level-1 engineer should take the level-1 job."""
    sc = Scenario(
        engineers=[Engineer(id="Expert", name="a", x=0, y=0, skills={"cmp": 3}),
                   Engineer(id="Generalist", name="b", x=20, y=0, skills={"cmp": 1})],
        jobs=[Job(id="J1", x=10, y=0, skill="cmp", min_level=1, earliest=0, latest=100)],
    )
    assert allocate(sc, Weights(), "greedy").assignments[0].tech_id == "Generalist"
    no_penalty = Weights(overqualification=0)
    assert allocate(sc, no_penalty, "greedy").assignments[0].tech_id in {"Expert", "Generalist"}


def test_insertion_reorders_route_by_time():
    """A job added later but due earlier is inserted in front, not appended."""
    sc = Scenario(
        engineers=[Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 2})],
        jobs=[Job(id="Late", x=50, y=0, skill="etch", priority=3, earliest=200, latest=300, duration=30),
              Job(id="Early", x=60, y=0, skill="etch", priority=1, earliest=0, latest=60, duration=30)],
    )
    res = allocate(sc, Weights(), "greedy")
    assert [s.job_id for s in res.routes[0].stops] == ["Early", "Late"]


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
