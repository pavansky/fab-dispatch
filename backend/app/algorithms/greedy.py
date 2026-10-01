"""Greedy: take jobs one at a time in dispatch order and give each the cheapest engineer.

Dispatch order is what a fab shift lead does by hand: bottleneck tools first, then the
tightest deadline. Fast and easy to explain, but a choice is never revisited, so an early
job can take the only engineer a later job could have used.
"""
from __future__ import annotations

from ..planner import Planner
from .base import Decision, decision


def run_greedy(p: Planner) -> dict[str, Decision]:
    order = sorted(p.jobs.values(), key=lambda j: (-j.priority, j.latest, j.earliest, j.id))
    decisions: dict[str, Decision] = {}
    for n, job in enumerate(order, 1):
        feasible, rejected = p.scan(job.id)
        if not feasible:
            continue
        best = feasible[0]
        p.commit(best)
        decisions[job.id] = decision(best, feasible, rejected, f"Dispatched #{n} in priority/deadline order; cheapest feasible was")
    return decisions
