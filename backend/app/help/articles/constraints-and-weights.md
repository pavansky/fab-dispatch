---
title: Constraints and cost weights
summary: The rules no plan may break, and the soft costs you can tune.
section: Planning
order: 3
keywords: [constraint, constraints, hard, soft, weight, weights, slider, sliders, cost, penalty, walking, travel, idle, wait, over-qualification, overqualification, workload, balance, priority reward, stability, tune, tuning, reset]
---

# Constraints and cost weights

## Hard constraints

A plan never breaks these. Every strategy is tested against them, on every fab:

- **Certification:** the engineer is certified for the job's tool family,
- **Level:** at or above the level the job needs (1–3),
- **Max jobs:** no engineer takes more jobs than their limit,
- **Start window:** work starts inside the job's window (a tool-down's response time),
- **Shift end:** all work finishes before the engineer's shift ends.

A job no engineer can do within these rules is **unassigned**, with the reason (for example
*4 not certified, 1 at max jobs*).

## Soft constraints: the cost weights

Everything else is a cost, in points. The **Cost weights** sliders set how much each one matters,
and every strategy re-solves as you drag.

| Weight | Default | Charged |
|---|---|---|
| Priority reward | 60 | A reward per priority point served (unserved work costs this much) |
| Walking | 4 | Per 100 m walked on the floor |
| Idle wait | 0.2 | Per minute an engineer waits for a job's window to open |
| Over-qualification | 8 | Per certification level above what the job needs |
| Workload balance | 5 | Per job the engineer already holds, so work spreads out |

In **live dispatch**, a sixth weight, **stability** (25), charges for moving a job to a different
engineer when re-planning, so people aren't reshuffled for tiny gains.

**Reset to defaults** restores every slider.

## Tuning tips

- Raise **Walking** when a metre of walking really costs more, for example on a floor where aisles
  force long detours. Heavier cleanroom garb makes people *slower*, which is the fab profile's
  walking speed (`walk_m_per_min`), not the cost per metre.
- **Over-qualification** charges for sending a level-3 engineer to a level-1 job, so a higher
  weight steers routine work to junior engineers *when a cheaper qualified option exists*. It does
  not hold anyone back: a plan still uses a senior engineer when they are the only one free. Keeping
  capacity in reserve for a fault that hasn't happened yet is not something the planner does.
- Raise **Priority reward** when unserved work is unacceptable, even at higher cost.
