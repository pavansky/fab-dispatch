# Algorithm comparison

All numbers are from `python -m scripts.benchmark --seeds 20` with default weights. Each preset is 20
seeded shifts of 14 engineers and 45 jobs. **Cost** is the full objective (walking + idle wait +
over-qualification + unserved-priority penalty; lower is better). **Lowest cost** counts the seeds
where a strategy had the cheapest plan. Every strategy is scored by the same constraint engine, so the
only difference is how it decides.

## 1. Results

### Quality by scenario

| Normal shift | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost |
|---|---|---|---|---|---|---|---|---|---|
| Greedy | 93.7 | 97.8 | 23.9 | 102.9 | 1819 | 1.7 | 924.5 | 1.5 | 0/20 |
| Hungarian | 96.1 | 97.9 | **15.8** | 85.5 | 2333 | **0.6** | 967.2 | 2.9 | 0/20 |
| Regret-2 | 94.7 | 97.1 | 22.2 | 97.3 | 1528 | 1.6 | 851.4 | 5.9 | 0/20 |
| ALNS | 98.0 | **98.4** | 22.0 | 86.1 | 1182 | 1.6 | 641.8 | 338 | 0/20 |
| PyVRP | **98.1** | **98.4** | 23.4 | **83.7** | **968** | 1.9 | **577.9** | 1074 | **20/20** |

| Litho crunch | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost |
|---|---|---|---|---|---|---|---|---|---|
| Greedy | 67.2 | 55.0 | 21.8 | 104.8 | 1596 | 2.0 | 2463.4 | 1.3 | 0/20 |
| Hungarian | 68.2 | 55.4 | **7.5** | 87.7 | 3162 | **0.9** | 2743.4 | 2.2 | 0/20 |
| Regret-2 | 67.9 | 55.2 | 19.2 | 102.6 | 1385 | 2.0 | 2389.4 | 5.0 | 0/20 |
| ALNS | 68.8 | **57.1** | 17.1 | 87.8 | 1088 | 2.0 | 2238.3 | 475 | 1/20 |
| PyVRP | **68.9** | **57.1** | 19.5 | 93.9 | **890** | 2.2 | **2200.9** | 671 | **19/20** |

| Excursion / surge | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost |
|---|---|---|---|---|---|---|---|---|---|
| Greedy | 90.8 | 89.8 | 8.9 | 104.3 | 2442 | 1.7 | 1384.6 | 1.4 | 0/20 |
| Hungarian | 93.1 | 91.3 | **4.5** | 88.5 | 3326 | **0.7** | 1444.1 | 2.7 | 0/20 |
| Regret-2 | 92.2 | 89.9 | 7.3 | 97.0 | 2381 | 1.6 | 1306.7 | 6.4 | 0/20 |
| ALNS | 94.6 | **91.8** | 7.6 | 93.5 | 1961 | 1.6 | 1074.4 | 358 | 0/20 |
| PyVRP | **94.8** | 91.5 | 9.0 | 91.6 | **1633** | 2.0 | **993.2** | 984 | **20/20** |

| Overstaffed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost |
|---|---|---|---|---|---|---|---|---|---|
| Greedy | 92.4 | 97.7 | 30.3 | 101.7 | 1787 | 1.7 | 947.9 | 1.5 | 0/20 |
| Hungarian | 96.8 | **98.7** | **17.9** | 85.5 | 2240 | **0.6** | 912.2 | 3.0 | 0/20 |
| Regret-2 | 95.3 | 97.7 | 30.6 | 98.3 | 1330 | 1.7 | 783.5 | 6.5 | 0/20 |
| ALNS | **98.1** | **98.7** | 27.9 | 84.1 | 1067 | 1.7 | 613.6 | 355 | 0/20 |
| PyVRP | **98.1** | **98.7** | 31.0 | **83.7** | **824** | 2.0 | **540.3** | 1113 | **20/20** |

### Distance from the proven optimum

20 small shifts (4 engineers × 12 jobs) solved exactly by route enumeration plus a set-partitioning
MILP (HiGHS). Gap = (strategy cost − optimum) / optimum.

| Strategy | Mean gap | Worst gap | Found the optimum |
|---|---|---|---|
| Greedy | 10.5% | 38.9% | 3/20 |
| Hungarian | 7.2% | 28.2% | 2/20 |
| Regret-2 | 4.7% | 15.9% | 6/20 |
| **ALNS** | **0.9%** | **6.7%** | **14/20** |
| PyVRP | 1.8% | 11.2% | 14/20 |

### Solve time (ms, one shift)

| Size | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| 14 engineers, 45 jobs | 2 | 3 | 8 | 346 | 1,209 |
| 30 engineers, 100 jobs | 6 | 16 | 45 | 1,965 | 2,727 |
| 60 engineers, 200 jobs | 27 | 76 | 328 | 3,036* | 3,355* |

\* Hit the 3 s safety cap before the iteration budget. Those plans are still good but not
reproducible, so they're kept out of the shared cache (see [DECISIONS.md](DECISIONS.md) D5).

## 2. What I learned

**1. Search beats any one-pass rule, by a lot.** PyVRP had the cheapest plan in 79 of 80 shifts. Against
the best one-pass method (regret-2) it costs 24–32% less in three presets and 8% less in litho crunch,
and serves about 3 points more jobs (1 point in litho crunch). Most of the saving is **idle wait**, which
falls by about a third: the one-pass methods commit jobs in an order that leaves engineers standing at
tools waiting for windows to open, and only re-sequencing whole routes fixes that.

**2. The method that's best for one objective isn't best for another, and the exact solver shows why.**
On small shifts **ALNS gets closer to the true optimum than PyVRP** (0.9% vs 1.8% mean gap, 6.7% vs 11.2%
worst). ALNS optimises our objective exactly, including the convex workload-balance term. PyVRP can't
express that term natively, so it optimises a slightly different problem very well. On full-size shifts,
PyVRP's raw search speed (C++, tens of thousands of moves per second) outweighs that mismatch. The
lesson: a solver is only as good as its fit to the actual objective, and measuring against a proven
optimum is what reveals it.

**3. Hungarian wins on response time and fairness, and loses on cost, for one reason.** Hungarian has
the fastest response to tool-downs in every preset (under half the next-best in litho crunch: 7.5 vs 17.1 min)
and by far the most even workload (std 0.6–0.9 vs 1.6–2.2). Each round gives every engineer at most one
job, chosen optimally for that round, so work spreads out and everyone's first job starts immediately.
But a round is optimal only for itself: later jobs get slotted where engineers wait for windows, so its
idle wait is the highest of all five in every preset. If the fab's top KPI is time-to-respond on a down
scanner, Hungarian is a defensible choice despite its cost.

**4. Greedy fails predictably, by spending scarce engineers too early.** `test_greedy_falls_into_the_trap`
is the minimal case: the critical job takes the nearest engineer, who was the only one able to reach a
second, tighter tool-down. Regret-2 exists to prevent exactly this ("place the job with the fewest good
options first"). It beats greedy on cost in every preset and found the optimum twice as often (6 vs 3).

**5. When certifications run out, no algorithm helps.** In litho crunch, all five hit the same ceiling:
67–69% coverage and 55–57% of bottleneck downs. The best search finds about 2 points more than
greedy. The Workforce view and the unassigned reasons ("no engineer on shift holds litho level 3+") point
to the real fix: cross-training or staffing. For a fab manager, that's often the most valuable output.

## 3. When does each approach win? (the brief's question)

| Situation | Best choice | Why |
|---|---|---|
| A job must be dispatched **the instant** it arrives; no batching window | Greedy, or regret insertion into the current plan | Milliseconds, explainable in one sentence. |
| **Contention**: many jobs competing for few qualified engineers, tight windows | Regret-2 at minimum, a search method ideally | One-at-a-time commitment strands jobs. |
| KPI is **time-to-respond** or **fairness** | Hungarian in rounds | Structurally spreads first jobs across everyone. Accept the idle-time cost. |
| KPI is **total cost or throughput**, and about 1 s is acceptable | PyVRP | Lowest cost in 79/80 shifts. |
| The objective has terms a library can't express (balance, stability, custom penalties) | ALNS | Optimises the exact objective. Closest to optimal on small shifts. |
| **Plenty of engineers** (overstaffed) | Any for bottleneck work; search for the rest | All cover about 98% of bottleneck downs. Greedy still drops PMs (92% vs 98% overall coverage) and costs 75% more than PyVRP. |
| **Certification shortage** | Fix staffing | All strategies hit the same ceiling. |

**When does the difference matter most?** Mostly where engineers are contended and windows are tight.
With slack engineers and wide windows, bottleneck work gets done whatever the method, and the
differences are cost and PMs. With scarce skills and tight SLAs, the order of decisions starts to decide
*whether* urgent work gets done, and batch and search methods pull ahead (surge: 90% → 92% of bottleneck
downs). At hard capacity limits the gap closes again, because nothing can be done.

## 4. Limitations and next steps

- **Synthetic data.** Real MES events and maintenance history would replace the generator and the
  repair catalogue. The interfaces (`Scenario`, `report_job`, `RepairIndex`) are where they'd plug in.
- **Stochastic durations.** The repair-history prediction gives a p10–p90 range. Planning against p80
  (buffers) instead of the mean would make schedules more robust.
- **Multi-engineer jobs and parts availability** aren't modelled (some PMs need two people or a part
  from stores).
- **Learning the weights.** The cost weights encode fab priorities by hand. Fitting them to past
  dispatcher decisions (inverse optimisation) would make the recommendations match how the site
  actually operates.
- **Scaling past one fab.** ALNS's pure-Python iterations slow past about 100 jobs (it hits the 3 s cap
  at 200). PyVRP or a compiled ALNS would be the path.
