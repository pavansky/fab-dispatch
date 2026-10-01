---
title: Benchmark and optimality
summary: Compare strategies over many shifts with confidence intervals, and measure the gap to the optimum.
section: Planning
order: 6
keywords: [benchmark, benchmarks, compare, many shifts, seeds, statistics, confidence interval, ci, bootstrap, tied, worse, significant, optimality, optimal, gap, optimum, exact, milp, measure gaps]
---

# Benchmark and optimality

One shift can be luck. The **Benchmark** view answers "which strategy is better in general?"
Running it needs the **dispatcher** role, because it's compute-heavy.

## Run a benchmark

Choose **Seeds per preset** (5, 10 or 20) and click **Run benchmark**. All five strategies solve that
many seeded shifts for every preset of your fab, at the engineer and job counts set in the left
panel. Results appear preset by preset, and repeat runs come from cache.

For each preset you get:

- A cost × latency chart of the **mean** result, with **95% confidence whiskers** on cost,
- The distribution of a metric you choose, one dot per shift,
- A table of means, and the **cost difference against the best strategy with its 95% interval**.

## Reading the verdicts

The differences are **paired**: strategies are compared on the same shifts, using a bootstrap.

- **Lowest cost:** the best mean cost.
- **Tied:** the interval includes zero, so the difference may be noise.
- **Worse:** the whole interval is above zero; a real difference.

**Best value** is the fastest strategy that's tied with the cheapest.

## Distance from the proven optimum

**Measure gaps** solves small shifts (4 engineers, 12 jobs) exactly, by enumerating every feasible
route and solving a set-partitioning problem, then shows each heuristic's mean gap. 0% means optimal.
