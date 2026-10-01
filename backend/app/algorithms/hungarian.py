"""Hungarian (Kuhn-Munkres) in rounds.

Each round builds an engineers x open-jobs cost matrix, where each cell is the marginal
cost of inserting that job into that engineer's current route, and solves it optimally
with scipy's ``linear_sum_assignment``. Every engineer gains at most one job per round;
rounds repeat until no feasible pair is left.

Within a round the matching is globally optimal, so it won't starve a job the way greedy
can. Across rounds it is still myopic: round 1 doesn't know what round 2 will need.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..planner import Planner
from .base import Decision, decision

INFEASIBLE = 1e9


def run_hungarian(p: Planner) -> dict[str, Decision]:
    decisions: dict[str, Decision] = {}
    techs = list(p.techs)
    rnd = 0
    while True:
        open_jobs = p.unplaced()
        if not open_jobs:
            break
        rnd += 1
        cost = np.full((len(techs), len(open_jobs)), INFEASIBLE)
        for r, t in enumerate(techs):
            for c, j in enumerate(open_jobs):
                ins = p.best_insertion(t, j)
                if ins.feasible:
                    cost[r, c] = ins.cost
        if (cost >= INFEASIBLE).all():
            break
        rows, cols = linear_sum_assignment(cost)
        picks = [(techs[r], open_jobs[c]) for r, c in zip(rows, cols, strict=True) if cost[r, c] < INFEASIBLE]
        # Snapshot explanations before committing: commits invalidate the insertion cache.
        pending = []
        for t, j in picks:
            feasible, rejected = p.scan(j)
            chosen = p.best_insertion(t, j)
            local = feasible[0]
            why = f"Round {rnd}: optimal matching of {len(techs)} engineers x {len(open_jobs)} open jobs chose"
            if local.tech_id != t:
                why = (
                    f"Round {rnd}: locally cheapest was {local.tech_id} ({local.cost:.1f}), but the "
                    f"globally optimal matching needed {local.tech_id} elsewhere, so it chose"
                )
            pending.append((chosen, decision(chosen, feasible, rejected, why)))
        for chosen, d in pending:
            p.commit(chosen)
            decisions[chosen.job_id] = d
    return decisions
