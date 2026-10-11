# Algorithm comparison

All numbers are from `python -m scripts.benchmark` with default weights. Each preset is 20 seeded
shifts of 14 engineers and 45 jobs. **Cost** is the full objective every strategy minimises
(`Planner.total_cost`: walking + idle wait + over-qualification + workload balance + the penalty
for unserved jobs; lower is better). **Lowest cost** counts the seeds where a strategy had the
cheapest plan. **Cost vs PyVRP** is the mean paired difference per shift with a paired bootstrap
95% confidence interval (percentile, 5,000 seeded resamples): a difference is real only when the
interval excludes zero. Every strategy is scored by the same constraint engine, so the only
difference is how it decides.

Two things to know before reading the tables:

- **Idle wait starts at the second stop.** An engineer leaves the home bay just in time for their
  first job, so slack before it is spent at the bay, not idle at a tool; waiting is charged from the
  second stop on. (Earlier versions charged the first leg too, and that was 83% of PyVRP's idle wait.)
- **The static benchmark assumes full foresight.** `--mode static` (the default, and every table in
  "Results") hands each strategy every job at t = 0, including tool-downs that in reality are only
  reported when they happen. `--mode revealed` replays each shift through the live-dispatch code
  instead; see "Quality with revealed information" for what that changes.

Numbers in this file were regenerated on a 4-core Intel Xeon @ 2.1 GHz container (Python 3.13);
the "ms" columns of the quality tables were measured with a second benchmark sharing those cores,
so treat them as indicative and use the solve-time table for timing. Tables marked
"(regenerate: `python -m scripts.benchmark --seeds 20`)" predate the idle-wait change and must be
re-run before they are quoted.

## 1. Results

### Quality by scenario (static: every job known at t = 0)

| Normal shift | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 94.6 | 97.4 | **19.7** | 94.9 | 234 | 1.1 | 845.9 | 6 | 0/20 | +175.3 [+146.6, +204.7] |
| Hungarian | 96.7 | **98.4** | 20.2 | 94.4 | 481 | **0.5** | 840.4 | 12 | 0/20 | +169.8 [+144.5, +196.0] |
| Regret-2 | 96.9 | **98.4** | 22.1 | 92.1 | 182 | 1.0 | 768.8 | 25 | 0/20 | +98.3 [+72.1, +127.5] |
| ALNS | 98.1 | **98.4** | 24.6 | 83.2 | 75 | 0.9 | 689.2 | 592 | 7/20 | +18.7 [+6.2, +31.3] |
| PyVRP | **98.3** | **98.4** | 24.3 | **76.3** | **49** | 1.4 | **670.5** | 1,169 | **13/20** | reference |

| Litho crunch | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 73.2 | 55.5 | 15.5 | 89.8 | 188 | 1.2 | 2174.1 | 7 | 0/20 | +117.8 [+76.2, +164.8] |
| Hungarian | 74.1 | 55.2 | **11.4** | 91.0 | 455 | **0.9** | 2196.8 | 12 | 0/20 | +140.5 [+104.8, +180.5] |
| Regret-2 | 74.3 | 55.2 | 17.0 | 85.0 | 101 | 1.2 | 2121.1 | 24 | 0/20 | +64.8 [+33.1, +100.0] |
| ALNS | **75.0** | **57.1** | 17.4 | 81.8 | 66 | 1.1 | **2045.0** | 982 | **15/20** | **−11.3 [−19.6, −3.4]** |
| PyVRP | **75.0** | **57.1** | 18.8 | **74.8** | **49** | 1.6 | 2056.3 | 1,005 | 5/20 | reference |

| Excursion / surge | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 92.2 | 91.1 | 8.7 | 96.8 | 800 | 1.2 | 1219.3 | 8 | 0/20 | +210.9 [+174.5, +249.7] |
| Hungarian | 92.5 | 91.5 | **5.9** | 88.6 | 1318 | **0.6** | 1293.4 | 14 | 0/20 | +285.1 [+226.4, +347.2] |
| Regret-2 | 93.0 | 90.2 | 8.2 | 91.9 | 589 | 1.2 | 1181.0 | 29 | 0/20 | +172.6 [+129.2, +223.9] |
| ALNS | 94.7 | **91.8** | 8.9 | 91.7 | 396 | 1.2 | 1033.7 | 761 | 4/20 | +25.4 [+14.6, +36.4] |
| PyVRP | **95.0** | 91.5 | 9.6 | **88.4** | **270** | 1.5 | **1008.3** | 1,137 | **16/20** | reference |

| Overstaffed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 95.3 | **98.7** | 28.3 | 93.1 | 241 | 1.1 | 804.9 | 6 | 0/20 | +147.8 [+125.2, +169.7] |
| Hungarian | 97.1 | **98.7** | **26.2** | 92.0 | 427 | **0.6** | 799.8 | 13 | 0/20 | +142.7 [+118.7, +167.5] |
| Regret-2 | 96.9 | 98.4 | 30.4 | 90.2 | 129 | 1.0 | 758.5 | 25 | 0/20 | +101.3 [+77.3, +125.9] |
| ALNS | **98.5** | **98.7** | 29.2 | 78.5 | 51 | 0.9 | **655.1** | 598 | 10/20 | −2.0 [−13.7, +8.2] |
| PyVRP | **98.5** | **98.7** | 35.0 | **74.2** | **34** | 1.4 | 657.1 | 1,111 | 10/20 | reference |

Reading the intervals: the one-pass rules (greedy, Hungarian, regret-2) are significantly more
expensive than PyVRP in every preset. Between the two search methods the picture is mixed: PyVRP
is significantly cheaper on the normal shift and the surge (+18.7 and +25.4 for ALNS, intervals
clear of zero), ALNS is significantly cheaper in the litho crunch (−11.3 [−19.6, −3.4]), and the
overstaffed shift is a tie. Reproduce: `python -m scripts.benchmark --seeds 20 --only quality`.

### Quality with revealed information (jobs known at `reported_at`)

The static benchmark lets every strategy plan around tool-downs it could not yet know about. This
study removes that foresight: each shift is replayed through `app/live.py`, exactly as the live
dashboard runs it. PMs are known at shift start; each tool-down becomes known at its
`reported_at` (the minute its window opens), the shift is re-planned there with started work
frozen on its engineer and the usual stability charge for moving a job, and the plan that was
actually executed is scored. **Cost** here is the realised plan's operating + workload cost (the
final re-plan's stability charge is left out so it is comparable with the static cost); **ms** is
the sum of every re-plan's solve time in the shift (25–40 re-plans, one per reveal time, each
under the 0.6 s live budget). 5 seeds per preset
(`python -m scripts.benchmark --seeds 5 --mode revealed`):

| Normal shift, revealed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | **96.0** | **88.4** | **16.6** | 93.0 | 25 | 1.0 | **850.6** | 44 | **3/5** | −123.2 [−246.9, +0.6] |
| Hungarian | 94.7 | 78.1 | 27.2 | 104.4 | 51 | **0.9** | 1042.9 | 36 | 0/5 | +69.2 [−71.1, +209.5] |
| Regret-2 | 95.1 | 80.8 | 22.0 | 93.5 | 34 | 1.0 | 959.9 | 77 | 1/5 | −13.8 [−122.3, +100.7] |
| ALNS | 94.7 | 79.1 | 20.2 | 86.3 | 14 | 1.0 | 977.8 | 3,886 | 0/5 | +4.1 [−102.5, +115.0] |
| PyVRP | 94.7 | 79.1 | 22.1 | **79.4** | **12** | 1.3 | 973.7 | 5,615 | 1/5 | reference |

| Litho crunch, revealed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | **74.2** | **48.9** | 14.3 | 89.1 | 15 | 1.1 | **2212.8** | 40 | **3/5** | −77.1 [−264.4, +33.3] |
| Hungarian | 73.8 | 46.5 | 19.7 | 98.4 | 15 | 1.1 | 2311.6 | 55 | 0/5 | +21.7 [−9.1, +42.2] |
| Regret-2 | 73.8 | 46.5 | 13.9 | 80.7 | 5 | **1.0** | 2281.3 | 73 | 0/5 | −8.6 [−24.6, +4.5] |
| ALNS | 73.3 | 45.2 | **12.3** | 83.9 | **1** | **1.0** | 2310.4 | 6,292 | 1/5 | +20.5 [−27.0, +90.3] |
| PyVRP | 73.8 | 46.5 | 17.9 | **76.3** | 3 | 1.4 | 2289.9 | 5,867 | 1/5 | reference |

| Excursion / surge, revealed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 89.3 | 77.6 | **6.6** | 83.8 | 11 | **1.0** | 1313.1 | 19 | 0/5 | −47.0 [−211.6, +77.3] |
| Hungarian | **91.1** | **82.6** | 9.7 | 94.8 | 2 | **1.0** | **1211.6** | 20 | **3/5** | −148.4 [−320.8, +27.0] |
| Regret-2 | 88.9 | 75.1 | 9.1 | 83.2 | 9 | **1.0** | 1357.2 | 23 | 0/5 | −2.9 [−128.6, +156.6] |
| ALNS | 89.8 | 77.2 | 8.9 | 81.9 | **0** | **1.0** | 1288.1 | 4,021 | 1/5 | **−71.9 [−135.6, −8.2]** |
| PyVRP | 88.9 | 74.8 | 9.4 | **77.6** | **0** | 1.3 | 1360.0 | 2,459 | 1/5 | reference |

| Overstaffed, revealed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 96.0 | 85.8 | 28.3 | 94.0 | 59 | 1.0 | 861.2 | 33 | 1/5 | −0.9 [−162.8, +161.0] |
| Hungarian | **96.4** | 83.3 | 40.6 | 108.1 | 77 | **0.9** | 904.0 | 39 | 1/5 | +41.8 [−176.8, +242.9] |
| Regret-2 | **96.4** | **87.1** | **26.0** | 89.0 | 14 | **0.9** | **829.1** | 71 | 0/5 | −33.0 [−163.1, +97.0] |
| ALNS | 94.7 | 78.9 | 27.5 | 93.0 | **4** | **0.9** | 934.3 | 3,625 | 1/5 | +72.1 [−96.2, +246.0] |
| PyVRP | 95.6 | 83.4 | 32.5 | **77.2** | 7 | 1.3 | 862.1 | 4,337 | **2/5** | reference |

Without foresight the ranking collapses. Nineteen of the twenty cost differences to PyVRP have a
confidence interval that includes zero; the one exception is ALNS on the surge (−71.9
[−135.6, −8.2]), where ALNS's stability-aware re-planning moved fewer people. Greedy, the cheapest
method to run, had the lowest realised cost in 7 of 20 shifts. Idle wait all but vanishes (a
tool-down is only known once its window is open, so nobody can be sent early to stand at it),
which is where most of the static saving came from. The static tables therefore measure how well a
method plans a *known* shift, which is the next-shift planning case; for live dispatch the
revealed numbers are the ones that matter, and on 5 seeds they do not separate the methods. Note
that PyVRP and ALNS re-plan 25–40 times per shift at 0.6 s each, two orders of magnitude more
compute than the one-pass rules for no measured gain here. A larger revealed study (20 seeds, and
re-planning policies that keep capacity in reserve) is the obvious next experiment.

### Distance from the proven optimum

20 small shifts (4 engineers × 12 jobs) solved exactly by route enumeration plus a set-partitioning
MILP (HiGHS). Gap = (strategy cost − optimum) / optimum.

| Strategy | Mean gap | Worst gap | Found the optimum |
|---|---|---|---|
| Greedy | 12.8% | 58.5% | 4/20 |
| Hungarian | 8.7% | 69.3% | 8/20 |
| Regret-2 | 2.7% | 12.4% | 11/20 |
| **ALNS** | **0.1%** | **1.6%** | **18/20** |
| PyVRP | 0.5% | 7.8% | 16/20 |

(Regenerated with the current code: `python -m scripts.benchmark --only gaps`.)

### Distance from the proven optimum at full size

The same exact method scales to full shifts: routes are short (4–6 jobs per engineer) and time
windows prune hard, so a 14 × 45 shift has about 39,000 feasible route sets (seed 0). Every one of
the 80 shifts below was **solved to proven optimality** (HiGHS, relative gap 0) when this table was
last generated: 20 s on average, 138 s at worst on an Apple M5 Pro. Each optimum is built and
costed by the same planner as the heuristics, and the study fails if any heuristic ever beats it.

The table below predates the idle-wait change and the ALNS cooling fix (regenerate:
`python -m scripts.benchmark --seeds 20`, i.e. `--only gaps-full`; about 30 minutes on a laptop):

| Strategy | Mean gap | Worst gap | Found the optimum |
|---|---|---|---|
| Greedy | 28.1% | 75.4% | 0/80 |
| Hungarian | 25.8% | 45.3% | 0/80 |
| Regret-2 | 19.4% | 49.7% | 0/80 |
| ALNS | 5.7% | 18.1% | 0/80 |
| **PyVRP** | **2.7%** | **10.0%** | **1/80** |

By preset, PyVRP's mean gap was 4.3% (normal), 0.9% (litho crunch), 2.1% (surge) and 3.6%
(overstaffed); ALNS's 7.6%, 1.7%, 5.5% and 7.9% (same regenerate marker).

**The litho-crunch gap is deflated by cost nobody can change.** In that preset most of the
objective is the penalty for jobs that no engineer on shift is certified for: every plan, the
optimum included, pays it, so a gap measured on the whole cost shrinks by construction. The gap
study therefore also prints the **gap on the changeable cost**, (strategy − optimum) / (optimum −
penalty of jobs no engineer in the instance can serve). One seed per preset with the current code
(`python -m scripts.benchmark --only gaps-full --gap-seeds 1`):

| Preset (seed 0) | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| Normal shift | 32.0% | 28.9% | 22.9% | 3.7% | 3.6% |
| Litho crunch | 6.4% | 5.3% | 4.3% | 0.9% | 2.2% |
| Excursion / surge | 28.4% | 27.9% | 12.4% | 4.0% | 2.0% |
| Overstaffed | 29.7% | 36.2% | 20.9% | 1.5% | 1.2% |
| Mean of the four | 24.2% | 24.6% | 15.1% | 2.5% | 2.3% |

Four shifts, 21 s per proof on average (36 s worst), 27,400 routes per shift. On seed 0 no job is
uncoverable by certification in any preset (the litho-crunch penalty there is capacity: one
qualified engineer who can't fit every job), so the changeable-cost gap equals the whole-cost gap.
Where the fixed penalty is real it matters: litho crunch on seeds 0–2
(`python -m scripts.benchmark --only gaps-full --gap-seeds 3 --presets litho_crunch`), where jobs
no engineer on shift is certified for are 31% of the optimum on average (47% on seed 1):

| Litho crunch, 3 seeds | Mean gap | Worst gap | Mean gap on the changeable cost |
|---|---|---|---|
| Greedy | 4.0% | 6.4% | 5.5% |
| Hungarian | 5.3% | 5.8% | 8.3% |
| Regret-2 | 2.5% | 4.3% | 3.4% |
| **ALNS** | **0.6%** | **0.9%** | **0.9%** |
| PyVRP | 1.4% | 2.2% | 1.9% |

So the litho crunch is not the "easy" preset the whole-cost gap suggests: on the cost a dispatcher
can change, Hungarian is 8.3% off and PyVRP 1.9%, not 5.3% and 1.4%. The capacity-bound part of
the penalty (jobs a qualified engineer exists for but can't reach in time) is left in the
changeable cost on purpose: a better plan can serve those.

**ALNS at a larger budget.** The earlier claim that 20,000 ALNS iterations lower its normal-shift
gap from 8.1% to 5.2% and no further was made without a script; it is now reproducible with
`python -m scripts.benchmark --only gaps-full --alns-iterations 20000` and carries the regenerate
marker until it is re-run with the new cooling schedule.

**Where the full proof stops scaling, and what replaces it.** Enumeration grows explosively: about
409,000 routes at 20 × 65 (27 minutes to prove on the laptop) and 8.3 million at 30 × 100, where a
direct MILP over every route didn't finish its first LP in hours. Column generation replaces it:
solve a small LP, use its prices to scan *all* routes for any that could improve the plan, add
those, repeat. The converged LP is a **certified lower bound** no plan can beat; an integer solve
over the generated routes gives a real plan. On a 14 × 45 shift with a known optimum it brackets
that optimum within 0.49% in 7 s (versus 83 s for the full proof), and its gaps match the exact ones.

| Shift size | n | Routes | Lower bound | Best plan | PyVRP above optimum | ALNS above optimum |
|---|---|---|---|---|---|---|
| 14 × 45 (proven) | 80 shifts | ~39,000 | exact | exact | 2.7% mean, 10.0% worst | 5.7% mean |
| 20 × 65 (proven, old code) | 1 shift | 409,000 | exact | exact | 3.9% | 6.3% |
| 30 × 100 (certified, old code) | **1 shift** | 8.3 million | 1828.0 | 1844.3 (within 0.89%) | 7.5–8.4% | 14.4–15.4% |

With the current code, 20 × 65 on three seeds (`python -m scripts.certified_bound 20 65 0 out/cg_20x65
--seeds 3`; 392,000–414,000 routes per shift, 37 s to enumerate, 2 s of column generation and
10–36 s of integer search each on the 4-core container):

| 20 × 65, seed | Lower bound | Best plan (within) | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|---|---|
| 0 | 916.5 | 921.6 (0.55%) | ≤36.7% | ≤19.0% | ≤19.5% | ≤8.3% | ≤9.9% |
| 1 | 718.6 | 726.1 (1.05%) | ≤46.9% | ≤30.6% | ≤32.8% | ≤10.7% | ≤16.1% |
| 2 | 843.2 | 852.4 (1.09%) | ≤46.1% | ≤29.5% | ≤32.2% | ≤11.0% | ≤7.7% |
| **mean of 3** | | | 43.2% | 26.4% | 28.2% | **10.0%** | 11.2% |

Each cell is a certified *maximum* gap to the optimum (the heuristic's distance to the lower bound;
the true gap is at most 1.1 points smaller). At 20 × 65 both search methods are about 10% off on
average, 2.5–4× their 14 × 45 one-seed gaps (3.6–3.7%), with ALNS ahead on two of three seeds. No
job on these shifts is uncoverable by certification, so the changeable-cost gap is the same.

The 30 × 100 bound took 13 minutes of enumeration, 12 s of column generation and 40 minutes of
integer search, **on one seed** (n = 1), under the old wait model. Read with that n in mind: a
single 30 × 100 reading of at most 8.4% above the optimum is inside the range already seen at
14 × 45, where the worst of 80 shifts was 10.0%, so on its own it does not establish that the gap
grows with size. The three-seed 20 × 65 measurement above does support it (about 10% mean against
2–4% at 14 × 45), and the 30 × 100 row is consistent with it. Reproduce at any size, seed count and
preset: `python -m scripts.certified_bound 30 100 0 out/cg_30x100 --seeds 3 --preset normal`.

### Scale: 20,000 engineers, measured

A company of 20,000 engineers on three shifts has about 6,700 on shift. Fabs, skills and areas split
that into independent subproblems; the study **plans 222 independent areas** of 30 engineers × 100
jobs, each a fresh `allocate` of its own shift (it is not one re-plan of a shared plan), in parallel.
It also drives 50 tool-downs into one live 30 × 100 shift through the real live-dispatch code, spread
over the whole 720-minute shift so the number of open jobs varies as it would in practice, and solves
three undecomposed problems. Reproduce: `python -m scripts.scale_study out/company`.

Measured on the 4-core Intel Xeon @ 2.1 GHz container, 2 workers (the laptop numbers this replaced,
46.7 s wall for 222 areas on 16 workers and a 217 ms live median, were taken before the idle-wait
change and without recording whether the cap bound; regenerate on that hardware with the command
above):

| What | Measured |
|---|---|
| Plan **222 independent areas** (6,660 engineers, 22,200 jobs, PyVRP, 2 workers) | **211 s** wall clock, 420 CPU-s; 1.87 s per area (p95 2.31 s); every area ran its full 1,000 iterations, **0/222 hit the 3 s cap** (so no capped-vs-uncapped comparison was needed; the script runs one when any area is capped) |
| **Live tool-down** re-planned through the real live-dispatch code (50 events at clocks 7–713 of 720, 10–54 open jobs at the event, ALNS) | **p50 247 ms, p95 542 ms**, max 602 ms; 0/50 hit the 0.6 s live cap |
| Tool-down rate implied by the generated company | 12,216 tool-downs across the 222 shifts = **0.28 per second** over the 720-minute shift |

At 0.28 tool-downs per second and 247 ms per re-plan, live re-planning needs about 7% of one core
(one core serves about 4 re-plans a second at the median). The same work *without* decomposition,
as one problem (one seed; `warm` is the regret-2 warm start both search methods pay before their
3 s search budget starts):

| One problem | Regret-2 | ALNS | PyVRP |
|---|---|---|---|
| 100 × 300 | 2.9 s, cost 3,224 | 6.7 s (2.8 warm + 3.6 search, **13 iterations**), cost 3,190 | 7.0 s (3.0 warm + 3.2 search, 550 iterations), cost 3,250 |
| 150 × 500 | 14.2 s, cost 6,012 | 19.1 s (15.2 warm + 3.2 search, 6 iterations), cost 6,012 | 33.3 s (15.1 warm + 3.8 search, 355 iterations), cost 6,105 |
| 300 × 1,000 | 148 s, cost 11,511 | 210 s (144 warm + 63 search, 5 iterations), cost 11,511 | killed by the container's memory limit while building PyVRP's 1,300-location matrices (regenerate: `python -m scripts.benchmark --seeds 20`, i.e. the scale study on a laptop; it measured 62 s, cost 6,994 there under the old wait model) |

Two findings. **Decomposition is required, not optional**: one big problem is slower than 222
areas in parallel and gives the search methods seconds of budget for hundreds of jobs. **ALNS's
budget at size was an accounting bug, now fixed, and the plan is still mostly the warm start.** Its
deadline used to start before the regret-2 warm start, so at 150 × 500 and up it ran *zero*
iterations and returned the regret-2 plan unchanged. With the deadline starting after the warm
start it runs 13 iterations at 100 × 300 (cost 3,224 → 3,190, 1% below regret-2 and 2% below PyVRP
at the same cap) and 5–6 at the larger sizes, where a single destroy-and-repair of a 500-job plan
takes most of the budget and no improvement was found. PyVRP at the same 3 s cap is 1–2% *worse*
than regret-2 at these sizes, because its 355–550 iterations are too few for a 300–500-job
instance; at 14 × 45 it has 1,000 iterations for 45 jobs. These are single runs on one seed.

### Solve time (ms, one shift)

Median of 5 runs per cell on a 4-core Intel Xeon @ 2.1 GHz container (Python 3.13.16; this is
what `python -m scripts.benchmark --only scaling` prints the platform for):

| Size | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| 14 engineers, 45 jobs | 6 | 10 | 20 | 511 | 1,018 |
| 30 engineers, 100 jobs | 23 | 55 | 127 | 2,824* | 2,062 |
| 60 engineers, 200 jobs | 109 | 252 | 1,163 | 4,057* | 4,225* |

\* Hit the 3 s safety cap before the iteration budget. Those plans are still good but not
reproducible, so they're kept out of the shared cache (see [DECISIONS.md](DECISIONS.md) D5). On an
Apple M5 Pro laptop the same cells measured 2 / 5 / 6 / 165 / 422 ms at 14 × 45 and 8 / 15 / 45 /
951 / 922 at 30 × 100 before the idle-wait change (regenerate:
`python -m scripts.benchmark --seeds 20`); Vercel's serverless CPU is roughly 3–5× slower than
that laptop.

### Sizing the search budget

How much quality each extra iteration buys (12 shifts, cost reduction relative to regret-2). The
shipped budgets, 300 ALNS and 1,000 PyVRP iterations, are **not equal wall time**: the last row
gives ALNS the iteration count that fits in PyVRP's shipped solve time on the same machine, which
is the fair comparison. The ALNS budget is now a real budget: its time limit starts after the
regret-2 warm start, as PyVRP's does, and its temperature cools to 0.1% of its start by the last
iteration whatever the budget (before, a fixed rate left 47% of the heat after 300 iterations, so
the search never went near-greedy).

Measured on the 4-core Xeon container (`python -m scripts.benchmark --only budgets`; an Apple M5 Pro
laptop is about 2.5× faster on these cells):

| Solver | Iterations | Cost below regret-2 | Mean solve ms |
|---|---|---|---|
| ALNS | 100 | 7.6% | 201 |
| ALNS | **300** (shipped) | 9.8% | 463 |
| ALNS | 600 | 10.7% | 993 |
| PyVRP | 250 | 10.4% | 326 |
| PyVRP | **1000** (shipped) | 11.5% | 987 |
| PyVRP | 3000 | 11.8% | 2,711 |
| ALNS | 640 (= PyVRP 1000's wall time) | 11.0% | 975 |

The curves flatten fast, and at equal wall time the two solvers are half a point apart (11.0% vs
11.5% below regret-2), so the shipped budgets, which give PyVRP about twice ALNS's time, understate
ALNS by about a point. The shipped budgets sit at the knee of both curves.

Going from 1,000 to 3,000 PyVRP iterations triples latency (on serverless, from about 1 s to past
the 3 s cap). Teams that value cost over latency can raise the budgets with
`FAB_PYVRP_ITERATIONS` / `FAB_ALNS_ITERATIONS`; the plan cache keys on the budget, so the change
is safe.

### Industrial AI: durations, failure predictions, a learned policy

Three studies on the questions a predictive-maintenance team asks first. All data is synthetic
(generated from each fab's fault catalogue with fixed seeds), so the numbers measure the method,
not a real fab. Each reproduces in seconds to minutes with the command shown.

**1. How good are the repair-time estimates?** Trained on each fab's 1,800-repair history and
tested on 600 repairs it never saw (`python -m scripts.duration_study out/durations`):

| Estimate (fab 1; fab 2 within 1.5 min) | MAE (min) | Repairs over the estimate | P90 coverage |
|---|---|---|---|
| Standard estimate per fault code (today's default) | 32.2 | 44% | n/a |
| Fault-code mean from history | 32.7 | 46% | 88.5% |
| k-NN over repair history (the app's retrieval) | 34.3 | 46% | **90.5%** |
| Quantile gradient boosting (P50/P90) | 34.0 | 52% | 86.0% |
| Oracle that knows the root cause | **15.5** | 48% | 90.0% |

No model beats the standard estimate on point accuracy, and that's the finding: the symptom text
identifies the fault code but says nothing about which root cause it is, and the root cause drives
about half the error (the oracle halves MAE). The history's real value is the **range**: k-NN's P90
is calibrated (90.5% of repairs finish within it), so a planner can protect bottleneck tools with
P90 instead of the mean. Getting below 32 minutes needs a signal of root cause (sensor data,
alarm codes, time since last PM), not a better regressor.

**2. Does planning on failure predictions pay?** Each tool-down is a failure at a known minute. A
mock predictor flags a share of them (recall) some minutes ahead (lead time) and raises false
alarms (precision), each a 45-minute inspection. Flagged failures enter the live plan at prediction
time; a repair started before the failure means no unplanned downtime. 40 shifts (14 × 45) replayed
through the real live-dispatch code, paired against reactive dispatch, bootstrap 95% CIs
(`python -m scripts.predictive_study out/predictive`):

| Predictor (lead 90 min, precision 70% unless stated) | Unplanned downtime saved per shift | Of which bottleneck tools | Failures prevented |
|---|---|---|---|
| Reactive (today) | baseline: 3,262 min | baseline: 1,342 min | 0% |
| Recall 30% | 729 min (621–838) | 317 min | 25% |
| Recall 60% | 1,550 min (1,413–1,687) | 683 min | 51% |
| Recall 90% | 2,194 min (2,061–2,331) | 1,045 min | 72% |
| Recall 60%, lead 30 min | 1,163 min | 546 min | 41% |
| Recall 60%, lead 120 min | 1,588 min | 668 min | 51% |
| Recall 60%, precision 40% | 999 min | 555 min | 42% |
| Recall 60%, precision 100% | 1,637 min | 711 min | 52% |

Recall matters most, then lead time; false alarms cost real capacity (precision 40% gives back about
a third of the saving) but never make prediction worse than reacting here. Past about 90 minutes of
lead, extra warning adds little: the limit becomes engineer capacity, which is the dispatcher's job.
The mock predictor's errors are random; a real one's would be correlated with tool age and load.

**3. Can a learned dispatch policy compete?** Greedy dispatch with a learned job order: each job
is scored on seven features (priority, window start, end and width, duration, certification level,
and scarcity = how few engineers can do it), and the weights are learned by the cross-entropy method,
a gradient-free policy-search form of reinforcement learning, on 40 training shifts (training takes
seconds; the shift generator is the environment, reward = minus plan cost). Tested on 40 unseen
shifts (10 per preset) against their proven optima
(`python -m scripts.learned_policy_study out/learned`):

| Strategy | Mean gap to optimum | Worst gap |
|---|---|---|
| Greedy, hand-written order | 27.4% | 75.4% |
| **Greedy, learned order** | **20.4%** | **42.6%** |
| Regret-2 | 18.3% | 49.7% |
| ALNS | 5.6% | 13.4% |
| PyVRP | 2.8% | 10.0% |

Learning the order is worth 7.0 gap points over the hand-written rule (95% CI 3.0 to 11.2) and
nearly halves the worst case, bringing a one-pass rule close to regret-2. It does not get near the
search methods: a learned *order* still commits each job once, and the remaining gap comes from
revisiting decisions, which search does. The proven optimum is what makes this a fair test; a
learned policy scored only against other heuristics could look better than it is. The useful role
for learning here is inside search (learning which ALNS moves to try), not replacing it.


## 2. What I learned

**1. With a known shift, search beats any one-pass rule; without foresight it doesn't.** In the
static benchmark PyVRP or ALNS had the cheapest plan in all 80 shifts, and the one-pass rules are
significantly more expensive in every preset (regret-2, the best of them, by +65 to +173 points,
every interval clear of zero). Most of that saving is **idle wait**: regret-2 leaves engineers
standing at tools for windows to open for 101–589 minutes a shift, PyVRP for 34–270, because only
re-sequencing whole routes removes that waiting. But the static benchmark hands every method the
tool-downs before they happen. Replayed through the live code with jobs revealed at `reported_at`
(5 seeds), 19 of the 20 cost differences to PyVRP are not significant, greedy had the cheapest
realised plan in 7 of 20 shifts, and idle wait all but disappears. The static result is the
next-shift planning case; the live case is still open.

**2. Small test cases flatter heuristics, and only a full-size proof shows it.** On small shifts
ALNS looked closest to optimal (0.9% vs PyVRP's 1.8%). At full size, proven optimal on 80 shifts
(before the idle-wait change; regenerate: `python -m scripts.benchmark --seeds 20`), the picture
flipped and widened: PyVRP was 2.7% from the optimum, ALNS 5.7%, and the one-pass rules 19–28%.
ALNS optimises our objective exactly, including the convex workload-balance term that PyVRP can't
express; with its budget now a real budget (time limit after the warm start, cooling to
near-greedy by the last iteration) it is within +19 to +25 points of PyVRP on two presets and
ahead on one. The lesson stands: measure against a proven optimum at the size you'll actually
run, not a size that's convenient to prove.

**3. Hungarian is the fairest method, and no longer the fastest to respond, for one reason.**
Hungarian has by far the most even workload (std 0.5–0.9 vs 0.9–1.6) and the fastest response in
the litho crunch, surge and overstaffed presets (5.9–26.2 min), though greedy edges it on the
normal shift. Each round gives every engineer at most one job, chosen optimally for that round, so
work spreads out and everyone's first job starts promptly. But a round is optimal only for itself:
later jobs get slotted where engineers wait for windows, so its idle wait is the highest of all
five in every preset (427–1,318 minutes). If the fab's top KPI is fairness, Hungarian is a
defensible choice despite its cost.

**4. Greedy fails predictably, by spending scarce engineers too early.** `test_greedy_falls_into_the_trap`
is the minimal case: the critical job takes the nearest engineer, who was the only one able to reach a
second, tighter tool-down. Regret-2 exists to prevent exactly this ("place the job with the fewest good
options first"). It beats greedy on cost in every static preset (by 46 to 77 points).

**5. When certifications run out, no algorithm helps.** In litho crunch, all five hit the same ceiling:
73–75% coverage and 55–57% of bottleneck downs. The best search finds about 2 points more than
greedy, and most of the remaining cost is the penalty for jobs nobody on shift can take (see "gap on
the changeable cost" above). The Workforce view and the unassigned reasons ("no engineer on shift
holds litho level 3+") point to the real fix: cross-training or staffing. For a fab manager, that's
often the most valuable output.

## 3. When does each approach win? (the brief's question)

| Situation | Best choice | Why |
|---|---|---|
| A job must be dispatched **the instant** it arrives; no batching window | Greedy, or regret insertion into the current plan | Milliseconds, explainable in one sentence, and in the revealed-information replay not measurably worse than search. |
| **Contention**: many jobs competing for few qualified engineers, tight windows | Regret-2 at minimum, a search method ideally | One-at-a-time commitment strands jobs. |
| KPI is **fairness** (and often time-to-respond) | Hungarian in rounds | Structurally spreads first jobs across everyone. Accept the idle-time cost. |
| KPI is **total cost or throughput** for a shift planned ahead, and about 1 s is acceptable | PyVRP or ALNS | Lowest static cost in 44/80 (PyVRP) and 36/80 (ALNS) shifts; one-pass rules are significantly dearer in every preset. |
| The objective has terms a library can't express (balance, stability, custom penalties) | ALNS | Optimises the exact objective; significantly cheaper than PyVRP in the litho crunch. |
| The plan is made **ahead of time** (next shift) and a minute or two is acceptable | Exact (set partitioning) | Proven optimal: 2.7% cheaper than PyVRP on average, up to 10% (old code; regenerate: `python -m scripts.benchmark --seeds 20`). 20 s typical at 14 × 45, but 27 min at 20 × 65; larger fabs need column generation. |
| **Plenty of engineers** (overstaffed) | Any for bottleneck work; search for the rest | All cover about 99% of bottleneck downs. Greedy still drops PMs (95% vs 98.5% overall coverage) and costs 23% more than PyVRP. |
| **Certification shortage** | Fix staffing | All strategies hit the same ceiling. |

**When does the difference matter most?** Mostly where engineers are contended and windows are tight.
With slack engineers and wide windows, bottleneck work gets done whatever the method, and the
differences are cost and PMs. With scarce skills and tight SLAs, the order of decisions starts to decide
*whether* urgent work gets done, and batch and search methods pull ahead (surge: 90.2% → 91.8% of
bottleneck downs). At hard capacity limits the gap closes again, because nothing can be done. And when
tool-downs are only known as they happen, none of this separates the methods on 5 seeds.

## 4. Why these algorithms, and not the newest ones in the literature?

I checked the current research (October 2026) before settling the lineup. Short answer: the lineup
contains the state of the art for the *routing core* of this problem (the VRPTW), I measured the
headroom above it exactly instead of guessing (2.7% on average), and the open research frontier is
somewhere else (uncertainty, not search). One honest caveat up front: the problem class here is the
technician routing and scheduling problem (TRSP), also studied as workforce scheduling and routing
(WSRP), and none of these strategies was run on a published TRSP instance set. The benchmarks that
back the "state of the art" label are VRPTW benchmarks, so the label covers the routing engine, not
the whole problem.

**The lineup spans every family, and its best member is the strongest open-source VRPTW engine.**

| Family | Here | Why it's in |
|---|---|---|
| Construction | Greedy, Regret-2 | What dispatchers do by hand; the baseline every method must beat |
| Assignment | Hungarian | Optimal one-job-per-round matching; best response time and fairness |
| Large neighbourhood search | ALNS | Optimises *our* exact objective; the family that recent LLM-designed operators improve ([VRPAgent](https://arxiv.org/pdf/2510.07073)) |
| Iterated local search | PyVRP | The pinned `pyvrp==0.14.0` ships iterated local search (ILS) only, with no population or genetic module. The competition wins belong to the hybrid genetic search (HGS) described in the [2024 PyVRP paper](https://arxiv.org/abs/2403.13795): first in the [2021 DIMACS VRPTW challenge](http://dimacs.rutgers.edu/programs/challenge/vrp/vrptw/) and in the static track of the [EURO meets NeurIPS 2022 competition](https://github.com/ortec/euro-neurips-vrp-2022-quickstart). The ILS is built on the same library's C++ local search and is what `pyvrp.solve` runs in this release |
| Exact | Set-partitioning MILP | Proves the optimum at full size, so every gap is measured, not guessed |

**The headroom is measured, and it's modest.** At full size, proven optimal on 80 shifts, the best
heuristic (PyVRP) is 2.7% from the optimum on average and 10% at worst (section 1). That is the most
any new solver could gain on this problem, and the exact method already captures it when there's time
to plan ahead. So the open question isn't "which newer heuristic?", it's how to get the optimum
*fast enough for live dispatch*: column generation (pricing routes instead of enumerating all of
them) is the established way to do that, and it's the next step for the solver.

**Why not neural solvers?** Learned routing solvers are measured against PyVRP's HGS on the VRPTW
([Neural Deconstruction Search](https://arxiv.org/pdf/2501.03715) reports matching or surpassing
state-of-the-art operations research methods on three VRP variants), or against earlier learned solvers: [RouteFinder](https://arxiv.org/pdf/2406.15007v2)'s
claim is beating prior learning-based methods across many VRP variants, not beating HGS. They need
GPU training for each instance distribution, can't express this objective's terms (convex workload
balance, plan stability, certification levels), and give no per-decision explanation, which the
brief requires.

**Why not LLM-evolved heuristics?** Methods like [EoH](https://arxiv.org/abs/2401.02051) (Liu et
al., ICML 2024), [ReEvo](https://arxiv.org/abs/2402.01145) (Ye et al., NeurIPS 2024), their
multi-objective successor [MEoH](https://arxiv.org/abs/2409.16867) (Yao et al., AAAI 2025),
[VRPAgent](https://arxiv.org/pdf/2510.07073) and [PyVRP+](https://arxiv.org/abs/2604.07872)
(up to 2.7% better than HGS on hard variants) are design-time tools: an LLM evolves operators
offline, evaluated by a solver like this one. They're a natural extension, evolving ALNS's destroy
and repair operators against this evaluator, not a replacement strategy to run per request. The
exact optimum here gives that kind of work something rare: a measured target (ALNS's 5.7% gap).

**The TRSP literature this sits in.** The skills-by-levels model here (a certification per tool
family, levels 1–3, a minimum level per job) is the one introduced for the ROADEF 2007 challenge and
formalised by Cordeau, Laporte, Pasin and Ropke (2010, *Journal of Scheduling* 13:393–409,
"Scheduling technicians and tasks in a telecommunications company", with a construction heuristic
and ALNS). Pillac, Guéret and Medaglia (2013, *Optimization Letters* 7:1525–1535) named the TRSP and
solved it with a parallel ALNS-based matheuristic; Kovacs et al. (2012, D4) applied ALNS to service
technician routing with skills. Xie, Potts and Bektaş (2017, *Journal of Heuristics* 23:471–500)
solved workforce scheduling and routing with iterated local search, the same family as the PyVRP
strategy here. Two surveys map the class: Castillo-Salazar, Landa-Silva and Qu (2016, *Annals of
Operations Research* 239:39–67, WSRP) and Paraskevopoulos, Laporte, Repoussis and Tarantilis (2017,
*European Journal of Operational Research* 263:737–754, resource-constrained routing and scheduling).
The strategies here were not run on any of those papers' instances; the comparison is internal, on
synthetic shifts, against a proven optimum. Running ALNS and the PyVRP mapping on a published TRSP
set would be the way to place them against that literature, and is listed in section 5.

**Where the real frontier is: uncertainty.** Recent technician-routing research has moved from
static to dynamic, stochastic problems: requests arriving during the day, uncertain repair times,
rework ([a 2026 survey](https://link.springer.com/article/10.1007/s00291-026-00865-y),
[learned dispatch policies](https://arxiv.org/pdf/2409.01815),
[value function approximation](https://doi.org/10.1287/trsc.2022.0434)). The live mode here is
rolling-horizon re-optimisation, the standard strong baseline in that literature. The gains left are
in anticipating what hasn't happened yet:

1. **Plan against a duration quantile.** Repair history already predicts p10–p90 per job; planning
   at p80 trades a little idle time for fewer broken schedules.
2. **Keep capacity in reserve.** A learned policy can hold a qualified engineer near the bottleneck
   tools instead of committing everyone, which matters most when a litho tool goes down mid-shift.

## 5. Limitations and next steps

### What the model does not capture

The constraint engine is deliberately small, and some of its simplifications would be wrong in a
real fab. Each of these shapes the results above:

- **Hard start-by windows, no lateness option.** A job either starts inside its window or is left
  unserved; there is no penalty for starting a bottleneck down ten minutes late. Together with the
  hard `max_jobs` cap this makes the *proven optimum* abandon priority-3 litho downs while a
  certified engineer sits idle: in the excursion preset, seed 2, J022 and J024 are dropped because no
  engineer can reach them inside the window, and the model has no way to prefer "late" over "never".
  A soft window with a lateness cost is the standard fix in the technician-routing literature.
- **`max_jobs` of 4–6 is a generator constant, not a fab fact.** Each synthetic engineer gets
  `max_jobs` drawn from {4, 5, 5, 6}. Real fabs limit a shift by hours, fatigue rules and handover,
  not by a job count; the cap exists so route enumeration stays finite for the exact solver.
- **One engineer per job.** Two-person jobs (some PMs, source rebuilds, heavy lifts) are not modelled.
- **No parts, no stores.** A repair is assumed to have its part on hand.
- **No handover, breaks, gowning or sub-fab travel.** Shift start to shift end is uninterrupted
  working time at floor level; a trip to the sub-fab or a gowning cycle between bays costs nothing.
- **Fixed durations regardless of who is sent.** A level-3 engineer and a level-1 engineer take the
  same time; the only skill effect is eligibility (and the over-qualification cost).
- **Manhattan distance on open rectangles.** Walking is axis-aligned distance between points; bay
  walls, aisles, doors and bay-to-bay routing are not drawn, so some walks are optimistic.
- **The fault catalogue's durations are illustrative.** Several standard estimates are short for the
  task named (an ESC swap at 180 min, a chamber wet clean and season at 240, a CD-SEM gun tip at
  140), and every family draws PM durations from the same {90, 120, 180, 240}. They are placeholders
  that make the shifts interesting at 14 × 45; a real fab supplies its own catalogue in the profile,
  and the benchmark figures scale with whatever it supplies.

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
  at 100 × 300 on this container). PyVRP, or a compiled ALNS, would be the path.
- **No external benchmark.** Every gap here is measured on this generator's shifts. Running the
  strategies on a published technician routing and scheduling instance set (section 4) would show
  where they stand against that literature, not only against each other.
