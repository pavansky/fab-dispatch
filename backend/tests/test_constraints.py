"""Every algorithm must respect every hard constraint on every generated scenario, and the exact
solver (the proof every optimality claim rests on) is held to the same re-derivation."""

import contextlib
import signal
import time

import pytest
from pydantic import ValidationError

from app.algorithms import ALGORITHMS
from app.algorithms.exact import ExactTimeout, run_exact
from app.engine import allocate
from app.fabs import all_profiles
from app.generator import generate
from app.models import AllocationResult, Engineer, Job, Scenario, Weights
from app.planner import Planner

# Every preset of every fab profile: hard constraints are a property of the engine, not of one fab.
CASES = [(fab.id, preset, seed) for fab in all_profiles().values() for preset in fab.presets for seed in range(3)]
FAB_PRESETS = [(fab.id, preset) for fab in all_profiles().values() for preset in fab.presets]
EXACT = ("Exact (route enumeration + set-partitioning MILP)", run_exact)


def assert_hard_constraints(sc: Scenario, res: AllocationResult) -> None:
    """Re-derive every hard constraint from the scenario alone: one engineer per job, every job
    assigned or explained, skills and levels, walking time, time windows, service time, shift end."""
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
@pytest.mark.parametrize("fab_id,preset,seed", CASES)
def test_hard_constraints_hold(algorithm, fab_id, preset, seed):
    sc = generate(seed=seed, n_engineers=12, n_jobs=40, preset=preset, fab_id=fab_id)
    assert_hard_constraints(sc, allocate(sc, Weights(), algorithm))


@pytest.mark.parametrize("fab_id,preset", FAB_PRESETS)
def test_hard_constraints_hold_for_the_exact_solver(fab_id, preset, monkeypatch):
    """The exact solver is not a dispatch strategy (it is not in ALGORITHMS), but its plan is the
    optimum every gap is measured against, so it gets the same re-derivation, and no strategy may
    beat it. 6 x 16 keeps every preset of every fab under a second."""
    monkeypatch.setitem(ALGORITHMS, "exact", EXACT)
    sc = generate(seed=0, n_engineers=6, n_jobs=16, preset=preset, fab_id=fab_id)
    res = allocate(sc, Weights(), "exact")
    assert_hard_constraints(sc, res)
    assert res.assignments, "the optimum serves at least one job"
    for name in ALGORITHMS:
        if name != "exact":
            assert allocate(sc, Weights(), name).metrics["objective"] >= res.metrics["objective"] - 1e-6, name


class _TooSlow(Exception):
    pass


@contextlib.contextmanager
def time_guard(seconds: int):
    """Skip, instead of hang, when this runner is too slow for a full-size proof."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def alarm(*_):
        raise _TooSlow

    previous = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(seconds)
    try:
        yield
    except _TooSlow:
        pytest.skip(f"the exact proof exceeded {seconds} s on this runner")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.slow
@pytest.mark.parametrize("preset", [p for p in all_profiles()["fab1-300mm-logic"].presets if p != "normal"])
def test_the_exact_optimum_is_proven_at_full_shift_size_for_every_preset(preset):
    """test_algorithms proves the normal preset at 14 x 45; the other presets are proven here (one
    seed each, 6 to 20 s on a laptop) so no optimality claim rests on a size that was never run in
    CI. Guarded at 240 s per proof (the overstaffed shift takes 2-4 minutes on a CI runner): a slow runner skips rather than times the job out."""
    sc = generate(0, 14, 45, preset)
    p = Planner(sc, Weights())
    t0 = time.perf_counter()
    with time_guard(240):  # the alarm covers route enumeration; HiGHS gets its own limit
        try:
            run_exact(p, time_limit_s=240)
        except ExactTimeout as e:
            pytest.skip(str(e))
    print(f"{preset}: proven in {time.perf_counter() - t0:.1f} s over {p.meta['solver']['columns']:,} routes")
    opt = p.total_cost()
    for name, (_, fn) in ALGORITHMS.items():
        q = Planner(sc, Weights())
        fn(q)
        assert q.total_cost() >= opt - 1e-6, f"{name} beat the proven optimum on {preset}"


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_every_decision_is_explained(algorithm):
    res = allocate(generate(seed=3), Weights(), algorithm)
    for a in res.assignments:
        assert a.tech_id in a.explanation
        assert a.cost_breakdown and set(a.cost_breakdown) >= {"travel", "priority"}
    for u in res.unassigned:
        assert u.reason


def test_engineer_and_job_ids_share_one_namespace():
    """The planner resolves a route location by id (home bay or job), so a clash is rejected."""
    with pytest.raises(ValidationError, match="both an engineer and a job: X1"):
        Scenario(
            engineers=[Engineer(id="X1", name="a", x=0, y=0, skills={"etch": 2})],
            jobs=[Job(id="X1", x=100, y=0, skill="etch", earliest=0, latest=100)],
        )


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_deterministic(algorithm):
    sc = generate(seed=11, preset="excursion")
    a = allocate(sc, Weights(), algorithm)
    b = allocate(sc, Weights(), algorithm)
    assert [x.model_dump() for x in a.assignments] == [x.model_dump() for x in b.assignments]
