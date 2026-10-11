"""Exact optimum for small shifts: route enumeration + set-partitioning MILP.

1. For each engineer, enumerate every feasible route of open jobs (depth-first, pruned by
   skill, level, time windows, shift end and max jobs). For each *set* of jobs keep only
   the cheapest feasible order.
2. Choose at most one route per engineer, with every job used at most once, minimising
   route cost (walking + waiting + over-qualification + workload term + live-mode
   stability, net of any frozen work) minus the priority reward of the jobs served. That
   is ``Planner.total_cost`` up to a constant, so the optimum is comparable with every
   heuristic's plan. This is a 0/1 MILP, solved with HiGHS through
   ``scipy.optimize.milp``, so there's no extra dependency.

Enumeration is exponential in route length, but routes here are short (an engineer does at
most 4-6 jobs a shift) and time windows prune hard: a full 14 x 45 shift has about 39,000
feasible route sets (seed 0), enumerated in about a second, and HiGHS proves the optimum in seconds.
So heuristics are measured against the proven optimum at full size, not just on toy shifts.
The guard is on the number of routes, which is what actually grows. It is not exposed in the
interactive UI.
"""

from __future__ import annotations

import os
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint
from scipy.optimize import milp as _milp
from scipy.sparse import csr_matrix

from ..planner import Planner
from .alns import explain_final

MAX_ROUTES = 2_000_000  # per engineer; a full-size shift needs a few thousand


class ExactTimeout(RuntimeError):
    """The MILP hit its time limit before proving optimality: no proof, so no plan is returned."""


def _threads_option() -> dict:
    """HiGHS starts a thread pool the size of the machine and ignores OMP_NUM_THREADS. When many
    proofs run side by side (the benchmark and study scripts), one thread each is much faster in
    total: the threads otherwise spend a third of their time contending. FAB_EXACT_THREADS=1 sets
    that; unset keeps HiGHS's default for a single proof."""
    n = os.environ.get("FAB_EXACT_THREADS")
    return {"threads": int(n)} if n else {}


class TooLarge(ValueError):
    pass


def enumerate_routes(p: Planner, tech_id: str) -> dict[frozenset, tuple[float, tuple[str, ...]]]:
    """Cheapest feasible order for every feasible set of open jobs this engineer could do.

    A route's cost is what adding those jobs to the engineer's frozen work changes
    ``Planner.total_cost`` by: soft costs, workload term and stability, minus the reward
    for the jobs it serves."""
    tech = p.techs[tech_id]
    base = list(p.frozen[tech_id].route)
    cap = tech.max_jobs - len(base)
    eligible = [j for j in p.unplaced() if p.tech_can_do(tech_id, j) is None]
    best: dict[frozenset, tuple[float, tuple[str, ...]]] = {frozenset(): (0.0, ())}
    count = 0

    def route_cost(seq: list[str]) -> float | None:
        sim, _ = p._simulate(tech_id, base + seq)
        if sim is None:
            return None
        k = len(base) + len(seq)
        soft = sum(p._soft(sim).values())
        return soft + p.w.workload_balance * k * (k - 1) / 2 + sum(p._moved(tech_id, j) for j in base + seq)

    # Frozen work is in every plan, so its cost is a constant: take it off every column.
    # The empty route then costs 0, the same as choosing no column for this engineer.
    fixed = route_cost([])
    assert fixed is not None  # the Planner already rejected infeasible frozen routes

    def cost_of(seq: list[str]) -> float | None:
        c = route_cost(seq)
        if c is None:
            return None
        return c - fixed - sum(p.w.priority_reward * p.jobs[j].priority for j in seq)

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
    return best


def run_exact(p: Planner, time_limit_s: float | None = None) -> dict:
    """Prove the optimum. ``time_limit_s`` caps the integer search (HiGHS cannot be interrupted
    from Python): on the limit ``ExactTimeout`` is raised, never a non-optimal plan."""
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
    t_index = {t: i for i, t in enumerate(techs)}
    rows, cols = [], []
    for col, (tid, seq) in enumerate(columns):
        rows.append(t_index[tid])
        cols.append(col)
        for j in seq:
            rows.append(len(techs) + j_index[j])
            cols.append(col)
    a = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(techs) + len(jobs), n))
    with warnings.catch_warnings():  # SciPy warns that "threads" is passed to HiGHS verbatim, as intended
        warnings.filterwarnings("ignore", "Unrecognized options", RuntimeWarning)
        res = _milp(
            c=np.array(costs),
            constraints=LinearConstraint(a, -np.inf, 1),
            integrality=np.ones(n),
            bounds=Bounds(0, 1),
            options={"disp": False, "mip_rel_gap": 0.0}
            | ({"time_limit": float(time_limit_s)} if time_limit_s else {})
            | _threads_option(),
        )
    if res.status == 1:  # time limit: the incumbent, if any, is not a proof
        raise ExactTimeout(f"MILP hit the {time_limit_s} s time limit: {res.message}")
    if res.status != 0:  # 0 = proven optimal; anything else is not a proof
        raise RuntimeError(f"MILP failed: {res.message}")
    for col in np.flatnonzero(res.x > 0.5):
        tid, seq = columns[col]
        for j in seq:
            assert p.append(tid, j) is not None
    p.meta["solver"] = {"columns": n, "mip_gap": getattr(res, "mip_gap", 0.0)}
    return explain_final(p, f"Proven optimal: set-partitioning MILP over {n} enumerated routes chose it.")
