"""PyVRP iterated local search: the state-of-the-art open-source VRPTW solver.

PyVRP (MIT) reaches about 0.2-0.8% of best-known solutions on the standard VRPTW
benchmarks. Mapping this problem onto it:

* engineer        -> one vehicle type (``num_available=1``) starting at their home bay,
                     or at their last started job in live mode
* max jobs        -> load capacity; every job delivers 1 unit
* job             -> optional client (``required=False``) whose prize is its priority reward
* start window    -> client ``tw_early``/``tw_late`` (PyVRP's tw_late is the latest *start*)
* shift end       -> vehicle ``tw_late``. Routes are open: they end at a sink depot
                     that every location reaches at zero cost
* skills, levels  -> one routing profile per distinct certification set. Arcs into a job
                     the profile can't do cost ``FORBIDDEN``, and over-qualification is
                     priced into the arc that enters the job
* walking, idle   -> arc cost carries walking. PyVRP's per-minute duration cost carries
                     waiting; the walking and service minutes it would also charge are
                     cancelled out exactly in the arc cost and the prize, using the same
                     integer rate PyVRP charges

PyVRP works in integers, so time is in tenths of a minute and cost in thousandths of a
point (fine enough that a waiting weight with two decimals, e.g. 0.25/min, is exact). The one term it can't express is the convex workload-balance penalty, so the
result is re-simulated and re-costed by our own planner. Every reported number therefore
comes from the same engine the other algorithms use.
"""

from __future__ import annotations

import time
from typing import NamedTuple

import numpy as np
from pyvrp import Activity, ActivityType, Model, ProblemData, Route, Solution, solve
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria

from ..config import get_settings
from ..planner import Planner
from .base import Decision
from .regret import run_regret

T = 10  # time units per minute
C = 1000  # cost units per point
FORBIDDEN = 10**9


def run_pyvrp(
    p: Planner, runtime_s: float | None = None, max_iterations: int | None = None, seed: int = 0
) -> dict[str, Decision]:
    if not p.open_jobs:
        return {}
    settings = get_settings()
    runtime_s = runtime_s if runtime_s is not None else p.time_limit_s or settings.solver_time_limit_s
    max_iterations = max_iterations if max_iterations is not None else settings.pyvrp_iterations
    t0 = time.perf_counter()
    w = p.w
    techs = list(p.techs.values())
    jobs = [p.jobs[j] for j in p.unplaced()]

    m = Model()
    sink = m.add_depot(m.add_location(0, 0, name="sink"), name="sink")

    # Each engineer starts where their committed work leaves them.
    starts, start_time, capacity = {}, {}, {}
    xs, ys = [0.0], [0.0]  # location coordinates in insertion order: sink, starts, jobs
    for e in techs:
        fr = p.frozen[e.id]
        sim = p.sim(e.id) if fr.route else None
        if fr.route:
            last = p.jobs[fr.route[-1]]
            x, y, ready = last.x, last.y, max(sim.end_time, fr.not_before)
        else:
            x, y, ready = e.x, e.y, max(float(e.shift_start), fr.not_before)
        starts[e.id] = m.add_depot(m.add_location(x, y, name=f"start-{e.id}"), name=f"start-{e.id}")
        start_time[e.id] = ready
        capacity[e.id] = e.max_jobs - len(fr.route)
        xs.append(x)
        ys.append(y)
    xs += [j.x for j in jobs]
    ys += [j.y for j in jobs]

    # PyVRP charges this per time unit of route duration. Only the waiting part is meant to
    # be charged: the walking and service time are cancelled using this same integer rate.
    unit_duration_cost = round(w.wait_min * C / T)
    # Engineers leaving the home bay are charged no idle wait before their first job (see
    # Planner._simulate); engineers resuming after started work are. The wait before a
    # first job is a constant per start->job arc, so it is cancelled on those arcs.
    depart = np.array([round(start_time[e.id] * T) for e in techs], dtype=np.int64)
    from_bay = np.array([not p.frozen[e.id].route for e in techs])
    tw_early = np.array([round(j.earliest * T) for j in jobs], dtype=np.int64)
    arcs = _arcs(np.array(xs), np.array(ys), p, unit_duration_cost, depart, from_bay, tw_early)

    for k, j in enumerate(jobs):
        service = round(j.duration * T)
        # Duration cost also charges the service time: add it back to the prize so it nets
        # out. The prize also carries the arc offset (see _arcs), which nets out the same way.
        prize = round(w.priority_reward * j.priority * C) + unit_duration_cost * service + arcs.offset[k]
        m.add_client(
            m.add_location(j.x, j.y, name=j.id),
            delivery=[1],
            service_duration=service,
            tw_early=round(j.earliest * T),
            tw_late=round(j.latest * T),
            prize=int(prize),
            required=False,
            name=j.id,
        )

    # One profile per certification set keeps the matrix count small.
    profiles: dict[tuple, object] = {}
    vt_order = []
    for e in techs:
        key = tuple(sorted(e.skills.items()))
        if key not in profiles:
            profiles[key] = m.add_profile(name=str(key))
        if capacity[e.id] <= 0 or start_time[e.id] >= e.shift_end:
            continue
        m.add_vehicle_type(
            1,
            capacity=[capacity[e.id]],
            start_depot=starts[e.id],
            end_depot=sink,
            tw_early=round(start_time[e.id] * T),
            start_late=round(start_time[e.id] * T),
            tw_late=round(e.shift_end * T),
            unit_distance_cost=1,
            unit_duration_cost=unit_duration_cost,
            profile=profiles[key],
            name=e.id,
        )
        vt_order.append(e.id)
    if not vt_order:
        return {}

    data = _with_matrices(m.data(), arcs, jobs, profiles, p)
    t_warm = time.perf_counter()
    initial = _warm_start(p, data, vt_order, [j.id for j in jobs])
    t_search = time.perf_counter()
    # MaxRuntime starts here, after the warm start, the same split as ALNS reports.
    stop = MultipleCriteria([MaxIterations(max_iterations), MaxRuntime(runtime_s)])
    res = solve(data, stop, seed=seed, collect_stats=False, display=False, initial_solution=initial)
    search_s = time.perf_counter() - t_search

    # Re-play PyVRP's routes through our planner, so every number uses one engine.
    client_ids = [c.name for c in data.clients()]
    decisions: dict[str, Decision] = {}
    for route in res.best.routes():
        tech_id = vt_order[route.vehicle_type()]
        for act in route.schedule():
            if act.type != ActivityType.CLIENT:  # depots appear in the schedule too
                continue
            jid = client_ids[act.idx]
            ins = p.append(tech_id, jid)
            if ins is None:
                continue  # infeasible under our exact rules (e.g. a FORBIDDEN arc); repaired below
            decisions[jid] = Decision(
                tech_id=tech_id,
                cost=round(ins.cost, 2),
                breakdown=ins.breakdown,
                explanation=(
                    f"Placed by PyVRP iterated local search over the whole shift "
                    f"({res.num_iterations} iterations) as stop "
                    f"{len(p.routes[tech_id])} of {tech_id}'s route, at marginal cost {ins.cost:.1f}."
                ),
            )
    # Anything PyVRP left out that still fits and pays for itself (cost < 0) gets a regret-insertion pass.
    for jid, d in run_regret(p).items():
        d.explanation = "Added after PyVRP by regret repair: " + d.explanation
        decisions[jid] = d
    p.meta["solver"] = {
        "iterations": res.num_iterations,
        "hit_time_cap": res.num_iterations < max_iterations,
        "warm_start_s": round(t_search - t_warm, 4),
        "search_s": round(search_s, 4),
        "runtime_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    return decisions


def _warm_start(p: Planner, data, vt_order: list[str], client_names: list[str]) -> Solution | None:
    """Seed the search with a regret-2 plan built on a scratch copy of the planner."""
    scratch = p.clone()
    run_regret(scratch)
    index = {n: i for i, n in enumerate(client_names)}
    routes = []
    for vt, tech in enumerate(vt_order):
        visits = [j for j in scratch.routes[tech][len(p.frozen[tech].route) :] if j in index]
        if visits:
            routes.append(Route(data, [Activity(ActivityType.CLIENT, index[j]) for j in visits], vt))
    try:
        return Solution(data, routes)
    except RuntimeError:
        return None


class _Arcs(NamedTuple):
    net: np.ndarray  # walking cost of every arc minus the walking time duration cost charges
    duration: np.ndarray  # walking time of every arc, in time units
    offset: np.ndarray  # per job: lifts its column so no arc into it is negative


def _arcs(
    xs: np.ndarray,
    ys: np.ndarray,
    p: Planner,
    unit_duration_cost: int,
    depart: np.ndarray,
    from_bay: np.ndarray,
    tw_early: np.ndarray,
) -> _Arcs:
    """Walking cost and time of every arc, in PyVRP's integer units.

    PyVRP charges ``unit_duration_cost`` for every time unit of a route, walking included,
    so the arc cost subtracts exactly that charge for its own walking time. The planner
    charges no idle wait before an engineer's first job from the home bay, and because the
    vehicle departs at a fixed time that wait is a constant per start->job arc, subtracted
    here the same way (``depart`` is each engineer's departure time, ``from_bay`` whether
    they start from the bay rather than from started work, ``tw_early`` each job's window
    open). Either can make an arc negative, which PyVRP doesn't handle (it stops visiting
    the job), so each job's column is lifted by ``offset`` and the same amount is added to
    its prize: a served job has exactly one incoming arc, so serving it costs the offset
    once and skipping it forfeits the offset once, and the comparison is unchanged.
    """
    w, speed = p.w, p.scenario.settings.walk_m_per_min
    n_fixed = 1 + len(depart)  # sink + one start per engineer come before the jobs
    metres = np.abs(xs[:, None] - xs[None, :]) + np.abs(ys[:, None] - ys[None, :])
    duration = np.rint(metres / speed * T).astype(np.int64)
    net = np.rint(w.travel_100m * metres / 100 * C).astype(np.int64) - unit_duration_cost * duration
    if len(tw_early):
        arrive = depart[:, None] + duration[1:n_fixed, n_fixed:]
        first_wait = np.maximum(0, tw_early[None, :] - arrive) * from_bay[:, None]
        net[1:n_fixed, n_fixed:] -= unit_duration_cost * first_wait
    # Arcs into jobs come from a start or another job; the sink (row 0) is never left.
    offset = np.maximum(0, -net[1:, n_fixed:].min(axis=0)) if net.shape[1] > n_fixed else np.zeros(0, np.int64)
    return _Arcs(net, duration, offset)


def _with_matrices(data: ProblemData, arcs: _Arcs, jobs, profiles: dict, p: Planner) -> ProblemData:
    """Build every profile's cost and walking-time matrix with NumPy in one pass.

    Location order matches insertion order: sink, one start per engineer, then jobs.
    """
    w = p.w
    n_fixed = arcs.net.shape[0] - len(jobs)  # sink + starts come before the jobs
    dist_mats, dur_mats = [], []
    for key in profiles:
        skills = dict(key)
        cost = np.full(arcs.net.shape, FORBIDDEN, dtype=np.int64)
        for k, job in enumerate(jobs):
            col = n_fixed + k
            level = skills.get(job.skill, 0)
            if level >= job.min_level:
                overq = round(w.overqualification * (level - job.min_level) * C)
                cost[1:, col] = arcs.net[1:, col] + overq + arcs.offset[k]
        cost[:, 0] = 0  # anything -> sink is free (open routes)
        np.fill_diagonal(cost, 0)
        assert (cost >= 0).all(), "PyVRP needs non-negative arc costs"
        dur = arcs.duration.copy()
        dur[:, 0] = 0
        dur[0, :] = FORBIDDEN // 1000  # never leave the sink
        dur[0, 0] = 0
        dist_mats.append(cost)
        dur_mats.append(dur)
    return data.replace(distance_matrices=dist_mats, duration_matrices=dur_mats)
