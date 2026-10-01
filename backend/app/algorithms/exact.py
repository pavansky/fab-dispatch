"""Exact optimum for small shifts: route enumeration + set-partitioning MILP.

1. For each engineer, enumerate every feasible route of open jobs (depth-first, pruned by
   skill, level, time windows, shift end and max jobs). For each *set* of jobs keep only
   the cheapest feasible order.
2. Choose at most one route per engineer, with every job used at most once, minimising
   route cost (walking + waiting + over-qualification + workload term) minus the
   priority reward of the jobs served. This is a 0/1 MILP, solved with HiGHS through
   ``scipy.optimize.milp``, so there's no extra dependency.

This is exponential in route length, so it's only for small instances (about 20 jobs
and 6 engineers). That's enough to measure how far each heuristic is from the true
optimum, which is what this module is for. It is not exposed in the interactive UI.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from ..planner import Planner
from .alns import explain_final

MAX_JOBS = 22
MAX_ROUTES = 400_000


class TooLarge(ValueError):
    pass


def enumerate_routes(p: Planner, tech_id: str) -> dict[frozenset, tuple[float, tuple[str, ...]]]:
    """Cheapest feasible order for every feasible set of open jobs this engineer could do."""
    tech = p.techs[tech_id]
    base = list(p.frozen[tech_id].route)
    cap = tech.max_jobs - len(base)
    eligible = [j for j in p.unplaced() if p.tech_can_do(tech_id, j) is None]
    best: dict[frozenset, tuple[float, tuple[str, ...]]] = {frozenset(): (0.0, ())}
    count = 0

    def cost_of(seq: list[str]) -> float | None:
        sim, _ = p._simulate(tech_id, base + seq)
        if sim is None:
            return None
        k = len(base) + len(seq)
        soft = sum(p._soft(sim).values())
        return (
            soft + p.w.workload_balance * k * (k - 1) / 2 - sum(p.w.priority_reward * p.jobs[j].priority for j in seq)
        )

    def dfs(seq: list[str]) -> None:
        nonlocal count
        if len(seq) >= cap:
            return
        for j in eligible:
            if j in seq:
                continue
            nxt = seq + [j]
            c = cost_of(nxt)
            if c is None:
                continue  # infeasible prefix: any extension is infeasible too (times only grow)
            count += 1
            if count > MAX_ROUTES:
                raise TooLarge(f"more than {MAX_ROUTES} routes for {tech_id}")
            key = frozenset(nxt)
            if key not in best or c < best[key][0]:
                best[key] = (c, tuple(nxt))
            dfs(nxt)

    dfs([])
    # Constant for frozen work, so empty routes of engineers with history compare fairly.
    return best


def run_exact(p: Planner) -> dict:
    if len(p.unplaced()) > MAX_JOBS:
        raise TooLarge(f"exact solver is limited to {MAX_JOBS} open jobs")
    jobs = p.unplaced()
    j_index = {j: i for i, j in enumerate(jobs)}
    techs = list(p.techs)
    columns: list[tuple[str, tuple[str, ...]]] = []
    costs: list[float] = []
    for tid in techs:
        for _, (c, seq) in enumerate_routes(p, tid).items():
            columns.append((tid, seq))
            costs.append(c)

    n = len(columns)
    a = np.zeros((len(techs) + len(jobs), n))
    for col, (tid, seq) in enumerate(columns):
        a[techs.index(tid), col] = 1
        for j in seq:
            a[len(techs) + j_index[j], col] = 1
    res = milp(
        c=np.array(costs),
        constraints=LinearConstraint(a, -np.inf, 1),
        integrality=np.ones(n),
        bounds=Bounds(0, 1),
        options={"disp": False},
    )
    if not res.success:
        raise RuntimeError(f"MILP failed: {res.message}")
    for col in np.flatnonzero(res.x > 0.5):
        tid, seq = columns[col]
        for j in seq:
            assert p.append(tid, j) is not None
    p.meta["solver"] = {"columns": n, "mip_gap": getattr(res, "mip_gap", 0.0)}
    return explain_final(p, f"Proven optimal: set-partitioning MILP over {n} enumerated routes chose it.")
