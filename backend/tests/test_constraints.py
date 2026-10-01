"""Every algorithm must respect every hard constraint on every generated scenario."""

import pytest

from app.algorithms import ALGORITHMS
from app.engine import allocate
from app.fabs import all_profiles
from app.generator import generate
from app.models import Weights

# Every preset of every fab profile: hard constraints are a property of the engine, not of one fab.
CASES = [(fab.id, preset, seed) for fab in all_profiles().values() for preset in fab.presets for seed in range(3)]


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
@pytest.mark.parametrize("fab_id,preset,seed", CASES)
def test_hard_constraints_hold(algorithm, fab_id, preset, seed):
    sc = generate(seed=seed, n_engineers=12, n_jobs=40, preset=preset, fab_id=fab_id)
    res = allocate(sc, Weights(), algorithm)
    engineers = {e.id: e for e in sc.engineers}
    jobs = {j.id: j for j in sc.jobs}
    speed = sc.settings.walk_m_per_min

    seen = [a.job_id for a in res.assignments]
    assert len(seen) == len(set(seen)), "a job was assigned twice"
    assert len(seen) + len(res.unassigned) == len(jobs), "every job is either assigned or explained"

    for route in res.routes:
        eng = engineers[route.tech_id]
        assert len(route.stops) <= eng.max_jobs
        t, (x, y) = float(eng.shift_start), (eng.x, eng.y)
        for stop in route.stops:
            job = jobs[stop.job_id]
            assert job.skill in eng.skills, "skill mismatch"
            assert eng.skills[job.skill] >= job.min_level, "under-certified"
            walk = abs(job.x - x) + abs(job.y - y)
            assert stop.arrival == pytest.approx(t + walk / speed, abs=0.2)
            assert job.earliest - 0.1 <= stop.start <= job.latest + 0.1, "outside time window"
            assert stop.start >= stop.arrival - 0.1
            assert stop.end == pytest.approx(stop.start + job.duration, abs=0.2)
            t, (x, y) = stop.end, (job.x, job.y)
        assert t <= eng.shift_end + 0.1, "shift overrun"


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_every_decision_is_explained(algorithm):
    res = allocate(generate(seed=3), Weights(), algorithm)
    for a in res.assignments:
        assert a.tech_id in a.explanation
        assert a.cost_breakdown and set(a.cost_breakdown) >= {"travel", "priority"}
    for u in res.unassigned:
        assert u.reason


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_deterministic(algorithm):
    sc = generate(seed=11, preset="excursion")
    a = allocate(sc, Weights(), algorithm)
    b = allocate(sc, Weights(), algorithm)
    assert [x.model_dump() for x in a.assignments] == [x.model_dump() for x in b.assignments]
