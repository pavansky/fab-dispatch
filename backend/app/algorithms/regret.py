"""Regret-2 insertion: a custom heuristic built for scarce skills.

At each step, for every open job compare its best and second-best engineer. The job
with the largest gap ("regret") is placed first, because it has the most to lose by
waiting. A job only one engineer can do has infinite regret, so it is placed before
anyone else can take that engineer.

That is the fab situation: lots of engineers can handle metrology, but maybe two people
on shift are level-3 on the EUV/immersion scanners.

The placement key is regret plus a quarter of the priority reward per priority level (15
points at the default weights). Typical regrets are only a few points, so in practice
priority orders first (bottleneck tool-downs, then tool-downs, then PMs) and regret orders
jobs within a level. A lower-priority job goes first only when its regret is more than 15
points per level higher, or when only one engineer can still take it.
"""

from __future__ import annotations

from ..planner import Planner
from .base import Decision, decision

SOLE_OPTION_REGRET = 1e6


def run_regret(p: Planner) -> dict[str, Decision]:
    decisions: dict[str, Decision] = {}
    open_jobs = set(p.unplaced())
    step = 0
    while open_jobs:
        best_job, best_key, best_scan = None, None, None
        for j in sorted(open_jobs):
            feasible, rejected = p.scan(j)
            if not feasible or feasible[0].cost >= 0:
                continue  # can't be placed now, or serving it would cost more than it earns
            regret = feasible[1].cost - feasible[0].cost if len(feasible) > 1 else SOLE_OPTION_REGRET
            key = (regret + p.w.priority_reward * 0.25 * p.jobs[j].priority, -feasible[0].cost)
            if best_key is None or key > best_key:
                best_job, best_key, best_scan = j, key, (feasible, rejected, regret)
        if best_job is None:
            break
        step += 1
        feasible, rejected, regret = best_scan  # type: ignore[misc]
        chosen = feasible[0]
        if regret >= SOLE_OPTION_REGRET:
            why = f"Step {step}: placed early because only one engineer could still do it;"
        else:
            why = f"Step {step}: highest regret {regret:.1f} (best vs second-best engineer);"
        p.commit(chosen)
        decisions[best_job] = decision(chosen, feasible, rejected, why + " chose")
        open_jobs.discard(best_job)
    return decisions
