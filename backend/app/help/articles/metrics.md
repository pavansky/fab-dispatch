---
title: Metrics reference
summary: Every metric on the scorecards and in the benchmark, and which direction is better.
section: Reference
order: 1
keywords: [metric, metrics, kpi, kpis, measure, coverage, jobs covered, bottleneck covered, priority-weighted, response, response time, p95, tail, unserved, walking per job, idle, idle wait, waiting, over-qualification, utilisation, utilization, workload spread, minutes, std, n/a, null, operating cost, objective, cost, points, pts, solve time, runtime, latency, scorecard, definition, mean, meaning]
---

# Metrics reference

Every view uses the same definitions. **↑** means higher is better, **↓** lower is better.

## Coverage

- **Jobs covered** (↑, %): share of known jobs assigned to someone.
- **Bottleneck downs covered** (↑, %): share of priority-3 tool-downs (tool-downs on the bottleneck
  family) assigned. Shown as **n/a** while the shift has no priority-3 work, for example early in a
  live shift before any bottleneck down is reported: there is nothing to cover yet, so it is not
  100%. The count of priority-3 jobs is reported alongside (`critical_jobs`).
- **Priority-weighted coverage** (↑, %): coverage where each job counts by its priority (3, 2 or 1).

## Speed and effort

- **Response to tool-downs** (↓, min): mean time from a tool-down's window opening to an engineer
  starting work on it, over the tool-downs that **are served**. A tool-down nobody takes is not
  averaged in; it is counted under **Unserved tool-downs**.
- **Response, p95** (↓, min): the slowest-but-one-in-twenty response among served tool-downs (nearest
  rank, so it is an actual job's response, not an interpolation). The mean hides a long tail; this
  shows it.
- **Unserved tool-downs** (↓, count): known tool-downs (any priority) that no engineer takes.
- **Walking per job** (↓, m): metres walked per job served.
- **Idle wait, all engineers** (↓, min): total minutes engineers wait for a job's window to open.
- **Over-qualification** (↓, levels): total certification levels above what jobs needed.
- **Engineer utilisation** (↑, %): hands-on work as a share of total shift time.
- **Workload spread** (↓, min): standard deviation of assigned service minutes per engineer, over
  every engineer on shift including those with no jobs. Lower is more even. This is what the UI
  shows (`workload_minutes_std`). The older **jobs**-based spread (`workload_std`, standard deviation
  of job counts over the same engineers) is still in the API for compatibility, but a 35-minute
  probe-card clean and a 240-minute chamber wet clean count the same there, so prefer minutes.

## Cost and speed of the solver

- **Operating cost** (↓, pts): the objective every strategy minimises: walking, idle wait,
  over-qualification and workload costs, plus the priority reward of any **unserved** work. See
  [Constraints and cost weights](help:constraints-and-weights).
- **Solve time** (↓, ms): how long the strategy took. Repeat plans come from cache.

## On the scorecards

**▲ / ▼ vs Greedy** shows each strategy's difference from the Greedy baseline, coloured by whether
it's better or worse.
