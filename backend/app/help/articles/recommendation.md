---
title: How the recommendation works
summary: Planning goals, the noise margin, and why a slower solver has to earn its latency.
section: Planning
order: 1
keywords: [recommend, recommended, recommendation, best, winner, why, goal, planning goal, best value, noise margin, tie, frontier, pareto, cost latency, chart]
---

# How the recommendation works

The recommendation card picks one plan using an explicit rule for the **planning goal** you choose.
It never declares a winner on a difference that could be noise.

## Planning goals

- **Best value: cost × latency** (default). Never gives up bottleneck coverage. Among plans whose
  cost is within the noise margin of the cheapest, it picks the **fastest to compute**.
- **Protect bottleneck tools.** Most bottleneck tool-downs covered, then the fastest response.
- **Maximise coverage.** The most priority-weighted work served, then the lowest cost.
- **Lowest operating cost.** The lowest total cost, whatever the solve time.

## The noise margin

On a single shift, re-sequencing one job can move the cost by a few points. So a cost difference
smaller than **2% of the cheapest plan, or 5 points, whichever is larger**, counts as a tie, not a
win. Calling a 1% difference a win would be a false positive. The shaded band on the chart shows
this margin.

## Best value, step by step

1. **Coverage guard:** drop any plan that covers fewer bottleneck tool-downs, or noticeably less
   priority-weighted work, than the best plan.
2. **Cheapest:** find the lowest-cost plan that's left.
3. **Ties:** every remaining plan within the noise margin of it is equivalent.
4. **Fastest:** of those, the one with the shortest solve time wins.

The card states which case applied, and the **trade-off** line names what you'd give up by picking
something else.

## The cost × latency chart

Each point is a strategy: operating cost (down is better) against solve time (left is better, on a
log scale). The line joins the **efficient frontier**: strategies no other strategy beats on both
cost and speed. A strategy off the frontier is dominated.
