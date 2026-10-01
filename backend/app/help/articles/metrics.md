---
title: Metrics reference
summary: Every metric on the scorecards and in the benchmark, and which direction is better.
section: Reference
order: 1
keywords: [metric, metrics, kpi, kpis, measure, coverage, jobs covered, bottleneck covered, priority-weighted, response, response time, walking per job, idle, idle wait, waiting, over-qualification, utilisation, utilization, workload spread, std, operating cost, objective, cost, points, pts, solve time, runtime, latency, scorecard, definition, mean, meaning]
---

# Metrics reference

Every view uses the same definitions. **↑** means higher is better, **↓** lower is better.

## Coverage

- **Jobs covered** (↑, %): share of known jobs assigned to someone.
- **Bottleneck downs covered** (↑, %): share of priority-3 tool-downs (bottleneck tools) assigned.
- **Priority-weighted coverage** (↑, %): coverage where each job counts by its priority (3, 2 or 1).

## Speed and effort

- **Response to tool-downs** (↓, min): mean time from a tool-down's window opening to an engineer
  starting work on it.
- **Walking per job** (↓, m): metres walked per job served.
- **Idle wait, all engineers** (↓, min): total minutes engineers wait for a job's window to open.
- **Over-qualification** (↓, levels): total certification levels above what jobs needed.
- **Engineer utilisation** (↑, %): hands-on work as a share of total shift time.
- **Workload spread** (↓, jobs): standard deviation of jobs per engineer. Lower is more even.

## Cost and speed of the solver

- **Operating cost** (↓, pts): the objective every strategy minimises: walking, idle wait,
  over-qualification and workload costs, plus the priority reward of any **unserved** work. See
  [Constraints and cost weights](help:constraints-and-weights).
- **Solve time** (↓, ms): how long the strategy took. Repeat plans come from cache.

## On the scorecards

**▲ / ▼ vs Greedy** shows each strategy's difference from the Greedy baseline, coloured by whether
it's better or worse.
