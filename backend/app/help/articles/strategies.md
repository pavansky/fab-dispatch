---
title: The five strategies
summary: Greedy, Hungarian, Regret-2, ALNS and PyVRP, and when each one wins.
section: Planning
order: 2
keywords: [algorithm, algorithms, strategy, strategies, greedy, hungarian, kuhn munkres, regret, regret-2, alns, large neighbourhood, pyvrp, vrp, local search, exact, milp, optimal, solver, heuristic, compare, difference]
---

# The five strategies

All five strategies share one constraint engine and one cost function. They differ only in **how
they decide the order and scope of assignments**, which is what makes the comparison fair.

## Greedy

Takes jobs in priority, then deadline, order, and gives each to the cheapest feasible engineer.
Never revisits a choice. Instant and the easiest to explain, but an early choice can block a later,
tighter job.

## Hungarian

Finds the optimal engineer-to-job matching for one round (Kuhn–Munkres), commits it, and repeats
until no feasible pair is left. The **fastest response to tool-downs** and the most even workload,
but it builds up idle time because it plans one round at a time.

## Regret-2

Places first the job with the most to lose: the largest gap between its best and second-best
engineer. That **protects scarce certifications**, so a job only one person can do isn't left
stranded.

## ALNS

Adaptive large neighbourhood search: repeatedly removes part of the plan and repairs it, keeping
changes that lower the cost. It optimises the exact objective, including workload balance. About 6%
from the proven optimum on full-size shifts.

## PyVRP

A state-of-the-art vehicle-routing solver (iterated local search, C++ core), warm-started from
Regret-2. The **lowest operating cost of the five**, mostly by cutting idle wait: about 3% from
the proven optimum on full-size shifts.

## Exact solver

Not a live dispatch option: it enumerates every feasible route and solves a set-partitioning
problem to find the **proven optimum**. It works at full shift size (about 20 seconds, up to a couple
of minutes), which suits planning ahead. The Benchmark view uses small shifts so the comparison
returns in seconds.

## When each one wins

| Situation | Best choice |
|---|---|
| You need an answer instantly | Greedy or Hungarian |
| Tool-downs must be answered fastest | Hungarian |
| Scarce certifications | Regret-2 |
| Lowest cost on a normal shift | PyVRP |
| Small shift, closest to optimal | ALNS |
| Certified engineers have run out | None: every strategy hits the same ceiling. It's a staffing problem. |
