"""Run an algorithm against a scenario and turn the final routes into results + metrics."""

from __future__ import annotations

import statistics
import time

from .algorithms import ALGORITHMS, Decision
from .models import AllocationResult, Assignment, Route, RouteStop, Scenario, Unassigned, Weights
from .planner import LEVEL_TOO_LOW, SKILL_MISSING, Frozen, Planner, describe_rejections


def allocate(
    scenario: Scenario,
    weights: Weights,
    algorithm: str,
    frozen: dict[str, Frozen] | None = None,
    open_jobs: set[str] | None = None,
    time_limit_s: float | None = None,
    previous_owner: dict[str, str] | None = None,
) -> AllocationResult:
    """Plan a shift. In live mode, ``frozen`` holds work already started and
    ``open_jobs`` the jobs known so far that may still be (re)assigned."""
    label, fn = ALGORITHMS[algorithm]
    planner = Planner(
        scenario, weights, frozen=frozen, open_jobs=open_jobs, time_limit_s=time_limit_s, previous_owner=previous_owner
    )
    t0 = time.perf_counter()
    decisions = fn(planner)
    runtime_ms = (time.perf_counter() - t0) * 1000

    assignments: list[Assignment] = []
    routes: list[Route] = []
    for tid, route in planner.routes.items():
        sim = planner.sim(tid)
        stops = []
        n_locked = len(planner.frozen[tid].route)
        for i, jid in enumerate(route):
            d = decisions.get(jid) or Decision(
                tid, 0.0, {}, f"Locked: {tid} had already started this job when the plan was revised."
            )
            assert d.tech_id == tid
            stops.append(
                RouteStop(
                    job_id=jid,
                    arrival=round(sim.arrivals[i], 1),
                    start=round(sim.starts[i], 1),
                    end=round(sim.ends[i], 1),
                    locked=i < n_locked,
                )
            )
            assignments.append(
                Assignment(
                    job_id=jid,
                    tech_id=tid,
                    sequence=i + 1,
                    arrival=round(sim.arrivals[i], 1),
                    start=round(sim.starts[i], 1),
                    end=round(sim.ends[i], 1),
                    travel_m=round(sim.legs_m[i], 1),
                    cost=d.cost,
                    cost_breakdown=d.breakdown,
                    explanation=d.explanation,
                    alternatives=d.alternatives,
                    rejections=d.rejections,
                )
            )
        routes.append(Route(tech_id=tid, stops=stops, metres=round(sim.metres, 1), end_time=round(sim.end_time, 1)))

    unassigned = [_why_unassigned(planner, jid) for jid in planner.open_jobs if jid not in decisions]
    return AllocationResult(
        algorithm=algorithm,
        label=label,
        assignments=assignments,
        unassigned=unassigned,
        routes=routes,
        metrics=_metrics(planner, runtime_ms),
        solver=planner.meta.get("solver", {}),
    )


def _why_unassigned(p: Planner, job_id: str) -> Unassigned:
    job = p.jobs[job_id]
    _, rejected = p.scan(job_id)
    n = len(p.techs)
    if rejected[SKILL_MISSING] == n:
        reason = f"No engineer on shift is certified on {job.skill}."
    elif rejected[SKILL_MISSING] + rejected[LEVEL_TOO_LOW] == n:
        reason = f"No engineer on shift holds {job.skill} level {job.min_level}+."
    else:
        qualified = n - rejected[SKILL_MISSING] - rejected[LEVEL_TOO_LOW]
        reason = f"{qualified} qualified engineer(s), but none had capacity: {describe_rejections(rejected)}."
    return Unassigned(job_id=job_id, reason=reason, rejections=dict(rejected))


def _metrics(p: Planner, runtime_ms: float) -> dict[str, float]:
    # Only jobs known to the planner count; in live mode future tool-downs aren't known yet.
    known = set(p.open_jobs) | {j for r in p.frozen.values() for j in r.route}
    jobs = [p.jobs[j] for j in sorted(known)]
    served = p.assigned_jobs()
    served_jobs = [j for j in jobs if j.id in served]
    critical = [j for j in jobs if j.priority == 3]
    total_pri = sum(j.priority for j in jobs) or 1

    starts: dict[str, float] = {}
    for tid, route in p.routes.items():
        for jid, s in zip(route, p.sim(tid).starts, strict=True):
            starts[jid] = s
    downs = [j for j in served_jobs if j.kind == "down"]
    response = [starts[j.id] - j.earliest for j in downs]

    used = [t for t, r in p.routes.items() if r]
    walk = sum(p.sim(t).metres for t in used)
    loads = [len(r) for r in p.routes.values()]
    shift = sum(t.shift_end - t.shift_start for t in p.techs.values()) or 1
    soft = sum(p.route_soft_cost(t) for t in p.routes)
    unserved_penalty = sum(p.w.priority_reward * j.priority for j in jobs if j.id not in served)

    def pct(a: float, b: float) -> float:
        return round(100 * a / b, 1) if b else 100.0

    return {
        "jobs": len(jobs),
        "assigned": len(served_jobs),
        "coverage_pct": pct(len(served_jobs), len(jobs)),
        "critical_coverage_pct": pct(sum(1 for j in critical if j.id in served), len(critical)),
        "priority_weighted_coverage_pct": pct(sum(j.priority for j in served_jobs), total_pri),
        "mean_response_min": round(statistics.fmean(response), 1) if response else 0.0,
        "walk_m_total": round(walk, 0),
        "walk_m_per_job": round(walk / len(served_jobs), 1) if served_jobs else 0.0,
        "wait_min_total": round(sum(p.sim(t).wait_min for t in used), 0),
        "overqualification_levels": sum(p.sim(t).overqualification for t in used),
        "utilization_pct": pct(sum(j.duration for j in served_jobs), shift),
        "engineers_used": len(used),
        "workload_std": round(statistics.pstdev(loads), 2) if loads else 0.0,
        "objective": round(soft + unserved_penalty, 1),
        "runtime_ms": round(runtime_ms, 2),
    }
