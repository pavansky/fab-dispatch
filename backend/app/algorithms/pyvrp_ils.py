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
                     cancelled out exactly in the arc cost and the prize

PyVRP works in integers, so time is in tenths of a minute and cost in hundredths of a
point. The one term it can't express is the convex workload-balance penalty, so the
result is re-simulated and re-costed by our own planner. Every reported number therefore
comes from the same engine the other algorithms use.
"""

from __future__ import annotations

import time

import numpy as np
from pyvrp import Activity, ActivityType, Model, ProblemData, Route, Solution, solve
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria

from ..config import get_settings
from ..planner import Planner
from .base import Decision
from .regret import run_regret

T = 10  # time units per minute
C = 100  # cost units per point
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

    clients = []
    for j in jobs:
        # Duration cost also charges service minutes; add them back to the prize so they net out.
        prize = w.priority_reward * j.priority + w.wait_min * j.duration
        clients.append(
            m.add_client(
                m.add_location(j.x, j.y, name=j.id),
                delivery=[1],
                service_duration=round(j.duration * T),
                tw_early=round(j.earliest * T),
                tw_late=round(j.latest * T),
                prize=round(prize * C),
                required=False,
                name=j.id,
            )
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
            unit_duration_cost=round(w.wait_min * C / T),
            profile=profiles[key],
            name=e.id,
        )
        vt_order.append(e.id)
    if not vt_order:
        return {}

    data = _with_matrices(m.data(), techs, jobs, profiles, p)
    initial = _warm_start(p, data, vt_order, [j.id for j in jobs])
    stop = MultipleCriteria([MaxIterations(max_iterations), MaxRuntime(runtime_s)])
    res = solve(data, stop, seed=seed, collect_stats=False, display=False, initial_solution=initial)

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
    # Anything PyVRP left out that still fits gets a regret-insertion pass.
    for jid, d in run_regret(p).items():
        d.explanation = "Added after PyVRP by regret repair: " + d.explanation
        decisions[jid] = d
    p.meta["solver"] = {
        "iterations": res.num_iterations,
        "hit_time_cap": res.num_iterations < max_iterations,
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


def _with_matrices(data: ProblemData, techs, jobs, profiles: dict, p: Planner) -> ProblemData:
    """Build every profile's cost and walking-time matrix with NumPy in one pass.

    Location order matches insertion order: sink, one start per engineer, then jobs.
    """
    w, speed = p.w, p.scenario.settings.walk_m_per_min
    locs = data.locations()
    xs = np.array([loc.x for loc in locs], dtype=float)
    ys = np.array([loc.y for loc in locs], dtype=float)
    metres = np.abs(xs[:, None] - xs[None, :]) + np.abs(ys[:, None] - ys[None, :])
    walk = metres / speed
    duration = np.rint(walk * T).astype(np.int64)

    n_fixed = 1 + len(techs)  # sink + starts come before the jobs
    base = w.travel_100m * metres / 100 - w.wait_min * walk
    dist_mats, dur_mats = [], []
    for key in profiles:
        skills = dict(key)
        cost = np.full(metres.shape, FORBIDDEN, dtype=np.int64)
        for k, job in enumerate(jobs):
            col = n_fixed + k
            level = skills.get(job.skill, 0)
            if level >= job.min_level:
                pts = base[:, col] + w.overqualification * (level - job.min_level)
                cost[:, col] = np.maximum(0, np.rint(pts * C)).astype(np.int64)
        cost[:, 0] = 0  # anything -> sink is free (open routes)
        np.fill_diagonal(cost, 0)
        dur = duration.copy()
        dur[:, 0] = 0
        dur[0, :] = FORBIDDEN // 1000  # never leave the sink
        dur[0, 0] = 0
        dist_mats.append(cost)
        dur_mats.append(dur)
    return data.replace(distance_matrices=dist_mats, duration_matrices=dur_mats)
