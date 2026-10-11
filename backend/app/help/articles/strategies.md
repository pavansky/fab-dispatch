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
but it builds up idle time because it plans one round at a time, so its plans cost more.

## Regret-2

Places first the job with the most to lose: the largest gap between its best and second-best
engineer. That **protects scarce certifications**, so a job only one person can do isn't left
stranded.

## ALNS

Adaptive large neighbourhood search: repeatedly removes part of the plan and repairs it, keeping
changes that lower the cost. It optimises the exact objective, including workload balance. About 6%
from the proven optimum on full-size shifts, and the closest of the five in the lithography crunch,
where scarce certifications dominate the cost.

## PyVRP

The PyVRP library's iterated local search (C++ core), warm-started from Regret-2. PyVRP is the
open-source solver whose hybrid genetic search won the recent VRPTW competitions; the version used
here runs its iterated local search, a different algorithm from the same library. It had the
**lowest cost in 50 of 80 benchmark shifts** (ALNS in 31), mostly by cutting idle wait, and is
about 4% from the proven optimum on full-size shifts. On the normal shift it is tied with ALNS; when
tool-downs are only known as they happen, it is rarely measurably cheaper than the simple strategies.

## Exact solver

Not a live dispatch option: it enumerates every feasible route and solves a set-partitioning
problem to find the **proven optimum**. It works at full shift size (about a minute on average on a
laptop, up to about 13 minutes for the hardest shift; it depends on the hardware), which suits
planning ahead but not a hosted request: the live app's API has a 60-second
limit, so the Benchmark view's *Measure gaps* proves small shifts (4 engineers × 12 jobs) and returns
in seconds. The full-size proofs, 80 shifts at 14 × 45, are in
[the analysis](https://pavansky.github.io/fab-dispatch/ANALYSIS/#distance-from-the-proven-optimum-at-full-size).

## When each one wins

| Situation | Best choice |
|---|---|
| You need an answer instantly | Greedy |
| Tool-downs arrive during the shift (live) | Greedy is a sound choice: in a replay with tool-downs revealed as they happen, it was never measurably dearer than PyVRP |
| Tool-downs must be answered fastest, or fairness matters most | Hungarian |
| Scarce certifications | Regret-2 at minimum; ALNS in a lithography crunch |
| Lowest cost on a shift known in advance | PyVRP or ALNS (tied on a normal shift; PyVRP ahead in a surge or when overstaffed) |
| Closest to the proven optimum at full shift size | PyVRP overall (3.9% mean gap over 80 proven shifts; ALNS 5.7%), ALNS in the lithography crunch. On small 4 × 12 shifts both are within 0.2%, which is why small shifts can't tell them apart: see [the analysis](https://pavansky.github.io/fab-dispatch/ANALYSIS/#distance-from-the-proven-optimum-at-full-size). |
| Certified engineers have run out | None: every strategy hits the same ceiling. It's a staffing problem. |
