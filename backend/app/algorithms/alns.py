"""Adaptive Large Neighbourhood Search (Ropke & Pisinger, 2006).

This is the method Kovacs et al. (2012) applied to service-technician routing with skill
levels, which is the closest problem in the literature to fab maintenance dispatch.
The loop is simple:

1. Start from the regret-2 plan.
2. *Destroy*: remove a handful of jobs using one of four operators.
     random   - any q jobs, for diversification
     worst    - the jobs whose removal saves the most cost
     related  - a seed job plus its neighbours in space, time window and tool family
                (Shaw removal). Related jobs are the ones worth swapping between engineers.
     route    - every open job on one engineer's route, so the plan can be rebuilt without them
3. *Repair*: reinsert open jobs with greedy (cheapest-first) or regret-2 insertion.
4. *Accept* the new plan if it's better, or with simulated-annealing probability if it's
   worse, so the search can climb out of local optima.
5. *Adapt*: operators that keep finding improvements are picked more often.

Unlike PyVRP, ALNS minimises *exactly* our objective, including the convex
workload-balance term. Being pure Python it runs a few hundred iterations per second
rather than PyVRP's tens of thousands.

It stops after a fixed number of iterations, with the time limit only as a safety cap,
so the same input always gives the same plan. Users don't see plans change on refresh,
and results can be cached safely.
"""
from __future__ import annotations

import math
import random
import time

from ..config import get_settings
from ..planner import Planner
from .base import Decision, decision
from .regret import run_regret

SCORES = (12.0, 6.0, 2.0)     # new global best, improved current, accepted worse
REACTION = 0.2                # how fast operator weights follow recent success
SEGMENT = 50                  # iterations between weight updates


def run_alns(p: Planner, runtime_s: float | None = None, seed: int = 0,
             max_iterations: int | None = None) -> dict[str, Decision]:
    if not p.open_jobs:
        return {}
    settings = get_settings()
    runtime_s = runtime_s if runtime_s is not None else p.time_limit_s or settings.solver_time_limit_s
    max_iterations = max_iterations if max_iterations is not None else settings.alns_iterations
    rng = random.Random(seed)
    deadline = time.perf_counter() + runtime_s
    run_regret(p)

    current = best = p.total_cost()
    best_snap = p.snapshot()
    destroy_ops = {"random": _random, "worst": _worst, "related": _related, "route": _route}
    repair_ops = {"greedy": _greedy_repair, "regret": _regret_repair}
    weights = {k: 1.0 for k in [*destroy_ops, *repair_ops]}
    scores = {k: 0.0 for k in weights}
    uses = {k: 0 for k in weights}
    # Start hot enough to accept a 5% worse plan half the time, then cool to near-greedy.
    temp = max(1.0, 0.05 * current / math.log(2))
    cooling = 0.9975
    it = best_it = 0

    while it < max_iterations and time.perf_counter() < deadline:
        it += 1
        d_name = _roulette(rng, {k: weights[k] for k in destroy_ops})
        r_name = _roulette(rng, {k: weights[k] for k in repair_ops})
        snap = p.snapshot()
        movable = [j for j in p.assigned_jobs() if j in p.open_jobs]
        q = max(1, min(len(movable), rng.randint(2, max(3, len(p.open_jobs) // 6))))
        destroy_ops[d_name](p, rng, q)
        repair_ops[r_name](p, rng)
        cost = p.total_cost()

        if cost < best - 1e-9:
            best, best_snap, best_it, current = cost, p.snapshot(), it, cost
            score = SCORES[0]
        elif cost < current - 1e-9:
            current, score = cost, SCORES[1]
        elif rng.random() < math.exp(-(cost - current) / temp):
            current, score = cost, SCORES[2]
        else:
            p.restore(snap)
            score = 0.0
        for k in (d_name, r_name):
            scores[k] += score
            uses[k] += 1
        temp *= cooling
        if it % SEGMENT == 0:
            for k in weights:
                if uses[k]:
                    weights[k] = (1 - REACTION) * weights[k] + REACTION * scores[k] / uses[k]
                scores[k], uses[k] = 0.0, 0

    p.restore(best_snap)
    p.meta["solver"] = {"iterations": it, "best_iteration": best_it, "hit_time_cap": it < max_iterations,
                        "operator_weights": {k: round(v, 2) for k, v in weights.items()}}
    return explain_final(p, f"ALNS kept this assignment: best plan found at iteration {best_it} of {it}.")


def explain_final(p: Planner, prefix: str) -> dict[str, Decision]:
    """Explain a finished plan job by job: take the job out, see who else could take it
    and at what cost, then put it back. Used by the whole-plan search methods."""
    out: dict[str, Decision] = {}
    for tid, route in p.routes.items():
        for jid in route[len(p.frozen[tid].route):]:
            scratch = p.clone()
            scratch.remove(jid)
            feasible, rejected = scratch.scan(jid)
            here = next((i for i in feasible if i.tech_id == tid), None)
            if here is None:  # its slot only works in its current sequence
                here = feasible[0] if feasible else None
            if here is None:
                out[jid] = Decision(tid, 0.0, {}, prefix)
                continue
            d = decision(here, feasible, rejected, prefix + " Re-inserting it alone would cost")
            d.tech_id = tid
            out[jid] = d
    return out


# ---------------------------------------------------------------- destroy operators
def _movable(p: Planner) -> list[str]:
    frozen = {j for f in p.frozen.values() for j in f.route}
    return sorted(j for j in p.assigned_jobs() if j not in frozen)


def _random(p: Planner, rng: random.Random, q: int) -> None:
    for j in rng.sample(_movable(p), min(q, len(_movable(p)))):
        p.remove(j)


def _worst(p: Planner, rng: random.Random, q: int) -> None:
    for _ in range(q):
        movable = _movable(p)
        if not movable:
            return
        gains = []
        for j in movable:
            tid = next(t for t, r in p.routes.items() if j in r)
            k = len(p.routes[tid])
            before = p.route_soft_cost(tid) + p.w.workload_balance * k * (k - 1) / 2
            scratch = p.clone()
            scratch.remove(j)
            after = scratch.route_soft_cost(tid) + p.w.workload_balance * (k - 1) * (k - 2) / 2
            gains.append((before - after - p.w.priority_reward * p.jobs[j].priority, j))
        gains.sort(reverse=True)
        # Randomised pick biased to the top (y^p rule from Ropke & Pisinger).
        p.remove(gains[int(len(gains) * rng.random() ** 4)][1])


def _related(p: Planner, rng: random.Random, q: int) -> None:
    movable = _movable(p)
    if not movable:
        return
    seed = p.jobs[rng.choice(movable)]

    def relatedness(jid: str) -> float:
        j = p.jobs[jid]
        dist = (abs(j.x - seed.x) + abs(j.y - seed.y)) / 100
        timing = abs(j.earliest - seed.earliest) / 60
        family = 0 if j.skill == seed.skill else 2
        return dist + timing + family

    for j in sorted(movable, key=relatedness)[:q]:
        p.remove(j)


def _route(p: Planner, rng: random.Random, q: int) -> None:
    candidates = [t for t, r in p.routes.items() if len(r) > len(p.frozen[t].route)]
    if candidates:
        tid = rng.choice(candidates)
        for j in p.routes[tid][len(p.frozen[tid].route):]:
            p.remove(j)


# ---------------------------------------------------------------- repair operators
def _greedy_repair(p: Planner, rng: random.Random) -> None:
    pending = p.unplaced()
    rng.shuffle(pending)
    pending.sort(key=lambda j: -p.jobs[j].priority)
    for j in pending:
        feasible, _ = p.scan(j)
        if feasible:
            p.commit(feasible[0])


def _regret_repair(p: Planner, rng: random.Random) -> None:
    run_regret(p)


def _roulette(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    r = rng.random() * total
    for k, w in weights.items():
        r -= w
        if r <= 0:
            return k
    return k
