"""Plan metrics: what they count, and what they refuse to claim."""

import statistics

import pytest

from app.engine import allocate
from app.generator import generate
from app.models import Engineer, Job, Scenario, Weights


def _shift(jobs: list[Job], n_engineers: int = 2) -> Scenario:
    return Scenario(
        engineers=[
            Engineer(id=f"E{i}", name=f"e{i}", x=0, y=0, skills={"etch": 3}, max_jobs=6) for i in range(n_engineers)
        ],
        jobs=jobs,
    )


def test_bottleneck_coverage_is_null_without_priority_3_work():
    """An early live shift with no bottleneck down yet must not read as "100% covered"."""
    sc = _shift([Job(id="J1", x=10, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=60, duration=30)])
    m = allocate(sc, Weights(), "greedy").metrics
    assert m["critical_jobs"] == 0
    assert m["critical_coverage_pct"] is None
    assert m["coverage_pct"] == 100.0


def test_bottleneck_coverage_counts_priority_3_jobs():
    sc = _shift(
        [
            Job(id="J1", x=10, y=0, skill="etch", priority=3, kind="down", earliest=0, latest=60, duration=30),
            Job(id="J2", x=20, y=0, skill="etch", priority=3, kind="down", earliest=0, latest=60, duration=30),
            Job(id="J3", x=30, y=0, skill="etch", priority=1, kind="pm", earliest=0, latest=240, duration=30),
        ]
    )
    m = allocate(sc, Weights(), "greedy").metrics
    assert m["critical_jobs"] == 2
    assert m["critical_coverage_pct"] == 100.0


def test_workload_spread_in_minutes_sees_what_job_counts_hide():
    """One engineer holds a 35-minute job, the other a 240-minute one: equal job counts (spread 0),
    very unequal minutes. Idle engineers count as zero in both."""
    sc = Scenario(
        engineers=[
            Engineer(id="E1", name="a", x=0, y=0, skills={"etch": 3}, max_jobs=1),
            Engineer(id="E2", name="b", x=0, y=0, skills={"etch": 3}, max_jobs=1),
            Engineer(id="E3", name="idle", x=0, y=0, skills={"cmp": 3}, max_jobs=1),
        ],
        jobs=[
            Job(id="J1", x=10, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=60, duration=35),
            Job(id="J2", x=20, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=60, duration=240),
        ],
    )
    m = allocate(sc, Weights(), "greedy").metrics
    assert m["assigned"] == 2
    assert m["workload_std"] == round(statistics.pstdev([1, 1, 0]), 2)
    assert m["workload_minutes_std"] == round(statistics.pstdev([35, 240, 0]), 1)


def test_response_tail_and_unserved_downs():
    """p95 response is a real served value at or above the mean; the response figures cover served
    tool-downs only, and the ones nobody could take are counted, not averaged in."""
    jobs = [
        Job(id="J1", x=10, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=100, duration=60),
        Job(id="J2", x=10, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=100, duration=60),
        Job(id="J3", x=10, y=0, skill="etch", priority=2, kind="down", earliest=0, latest=100, duration=60),
        # Needs a certification nobody holds, so it can never be served.
        Job(id="J4", x=10, y=0, skill="litho", priority=2, kind="down", earliest=0, latest=100, duration=60),
    ]
    m = allocate(_shift(jobs, n_engineers=1), Weights(), "greedy").metrics
    assert m["assigned"] == 2  # the third starts after its window closes
    assert m["unserved_downs"] == 2
    assert m["response_p95_min"] >= m["mean_response_min"] > 0
    assert m["response_p95_min"] == pytest.approx(60, abs=1)  # the second job starts when the first ends


@pytest.mark.parametrize("algorithm", ["greedy", "regret"])
def test_generated_shift_metrics_are_consistent(algorithm):
    sc = generate(3, 14, 45, "normal", "fab1-300mm-logic")
    m = allocate(sc, Weights(), algorithm).metrics
    assert m["critical_jobs"] == sum(1 for j in sc.jobs if j.priority == 3) > 0
    assert 0 <= m["critical_coverage_pct"] <= 100
    assert m["unserved_downs"] == sum(1 for j in sc.jobs if j.kind == "down") - sum(
        1 for a in allocate(sc, Weights(), algorithm).assignments if sc.jobs[int(a.job_id[1:]) - 1].kind == "down"
    )
    assert m["response_p95_min"] >= m["mean_response_min"]
    assert m["workload_minutes_std"] >= 0
