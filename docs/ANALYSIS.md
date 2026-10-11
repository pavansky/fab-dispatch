# Algorithm comparison

All numbers are from `python -m scripts.benchmark` with default weights. Each preset is 20 seeded
shifts of 14 engineers and 45 jobs. **Cost** is the full objective every strategy minimises
(`Planner.total_cost`: walking + idle wait + over-qualification + workload balance + the penalty
for unserved jobs; lower is better). **Lowest cost** counts the seeds where a strategy had the
cheapest plan (a tie counts for each strategy in it). **Cost vs PyVRP** is the mean paired
difference per shift with a paired bootstrap 95% confidence interval (percentile, 5,000 seeded
resamples): a difference is real only when the interval excludes zero. Every strategy is scored by
the same constraint engine, so the only difference is how it decides.

**What changed in 2.9.0 and why the numbers moved.** Every table below was regenerated, and most
numbers differ from 2.8.0 for six reasons. The cost that "Lowest cost" and the gap tables compare is
now the one objective every solver minimises, workload balance included. The one-pass rules and the
repair steps only insert a job when that lowers the total cost. No idle wait is charged before an
engineer's first job (see below). Priority 3, and so "Bottleneck %", now means a tool-down on the
fab's constraint tool family and nothing else. The *Overstaffed* preset adds one certified engineer
and wider windows instead of denser cross-training, and cross-trained engineers can now take some
constraint-family PMs. And a second benchmark mode replays each shift with tool-downs revealed only
when they happen.

Two things to know before reading the tables:

- **Idle wait starts at the second stop.** An engineer leaves the home bay just in time for their
  first job, so slack before it is spent at the bay, not idle at a tool; waiting is charged from the
  second stop on. (Earlier versions charged the first leg too, and that was 83% of PyVRP's idle wait.)
- **The static benchmark assumes full foresight.** `--mode static` (the default, and the first four
  tables in "Results") hands each strategy every job at t = 0, including tool-downs that in reality
  are only reported when they happen. `--mode revealed` replays each shift through the live-dispatch
  code instead; see "Quality with revealed information" for what that changes.

Numbers in this file were regenerated for 2.9.0 on an Apple silicon MacBook Pro (18 cores, Python
3.14.7), except where a section names other hardware. The revealed-information numbers come from a
seeded run of identical code on a 4-core Linux container; the static quality numbers were run on both
machines and came out identical. The "ms" columns are indicative (other studies shared the machine);
use the solve-time table for timing.

## 1. Results

### Quality by scenario (static: every job known at t = 0)

| Normal shift | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 94.7 | 98.3 | 23.1 | 91.9 | 229 | 1.1 | 805.2 | 2 | 0/20 | +177.0 [+140.8, +212.5] |
| Hungarian | 96.3 | **99.0** | **21.5** | 97.6 | 574 | **0.5** | 832.8 | 3 | 0/20 | +204.6 [+170.8, +244.4] |
| Regret-2 | 96.6 | **99.0** | 29.5 | 94.4 | 183 | 1.0 | 760.5 | 6 | 0/20 | +132.3 [+108.8, +156.0] |
| ALNS | **98.8** | **99.0** | 30.9 | 82.2 | **49** | 1.0 | 639.4 | 153 | 9/20 | +11.3 [−2.1, +27.3] |
| PyVRP | 98.7 | **99.0** | 29.0 | **74.3** | **49** | 1.4 | **628.2** | 309 | **11/20** | reference |

| Litho crunch | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 72.7 | 36.0 | 16.8 | 87.9 | 183 | 1.3 | 2258.4 | 1 | 0/20 | +112.2 [+82.0, +143.3] |
| Hungarian | 73.2 | 36.1 | **15.7** | 98.9 | 455 | **0.9** | 2285.4 | 2 | 0/20 | +139.2 [+108.1, +172.4] |
| Regret-2 | 73.3 | 36.1 | 21.8 | 89.7 | 93 | 1.2 | 2203.2 | 5 | 1/20 | +57.0 [+28.2, +90.0] |
| ALNS | **74.0** | **37.5** | 21.6 | 80.9 | 58 | 1.2 | **2134.9** | 191 | **15/20** | **−11.3 [−17.9, −5.2]** |
| PyVRP | **74.0** | **37.5** | 23.4 | **78.7** | **53** | 1.5 | 2146.2 | 194 | 6/20 | reference |

| Excursion / surge | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 93.1 | 88.5 | 9.7 | 93.1 | 910 | 1.2 | 1186.1 | 2 | 0/20 | +274.2 [+222.5, +326.9] |
| Hungarian | 94.1 | 89.1 | **7.4** | 89.7 | 1,232 | **0.7** | 1175.4 | 3 | 0/20 | +263.5 [+231.2, +297.1] |
| Regret-2 | 94.8 | 90.0 | 10.5 | 97.1 | 543 | 1.1 | 1052.1 | 6 | 0/20 | +140.2 [+110.4, +171.5] |
| ALNS | 96.1 | **90.4** | 11.5 | 88.9 | 323 | 1.2 | 931.1 | 154 | 4/20 | +19.2 [+8.0, +30.9] |
| PyVRP | **96.2** | **90.4** | 12.4 | **86.7** | **247** | 1.4 | **911.9** | 263 | **16/20** | reference |

| Overstaffed | Coverage % | Bottleneck % | Response min | Walk m/job | Idle wait min | Load std | **Cost** | ms | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Greedy | 93.5 | **100.0** | 33.5 | 93.6 | 170 | 1.0 | 776.4 | 2 | 0/20 | +192.9 [+158.1, +228.1] |
| Hungarian | 97.1 | **100.0** | **31.2** | 94.7 | 388 | **0.5** | 746.6 | 3 | 0/20 | +163.1 [+134.0, +193.5] |
| Regret-2 | 97.0 | **100.0** | 40.2 | 95.7 | 109 | 1.0 | 712.7 | 6 | 0/20 | +129.2 [+104.6, +157.2] |
| ALNS | **98.8** | **100.0** | 38.7 | 82.1 | 26 | 1.0 | 604.0 | 160 | 3/20 | +20.5 [+12.8, +28.3] |
| PyVRP | **98.8** | **100.0** | 41.8 | **75.3** | **16** | 1.3 | **583.4** | 312 | **17/20** | reference |

Reading the intervals: the one-pass rules (greedy, Hungarian, regret-2) are significantly more
expensive than PyVRP in every preset. Between the two search methods the picture is mixed. On the
normal shift they are tied (ALNS +11.3 [−2.1, +27.3], the interval includes zero). PyVRP is
significantly cheaper on the surge (+19.2 [+8.0, +30.9] for ALNS) and on the overstaffed shift
(+20.5 [+12.8, +28.3]). ALNS is significantly cheaper in the litho crunch (−11.3 [−17.9, −5.2]).
Over all 80 shifts PyVRP had the lowest cost in 50, ALNS in 31 and regret-2 in 1 (the litho crunch
has two ties, so its column adds up to 22). Reproduce:
`python -m scripts.benchmark --seeds 20 --only quality`.

**Why litho-crunch bottleneck coverage is 36–37.5%, not the 55–57% of 2.8.0.** It is a change of
definition, not a regression. Priority 3 used to include critical downs on other tool families; it
now counts only tool-downs on the constraint family (lithography in fab 1). In the litho crunch
those are exactly the jobs few engineers on shift are certified for, so the share covered is lower,
and about the same for every method. The overstaffed preset covers 100% because it now adds a
certified engineer.

### Quality with revealed information (jobs known at `reported_at`)

The static benchmark lets every strategy plan around tool-downs it could not yet know about. This
study removes that foresight: each shift is replayed through `app/live.py`, exactly as the live
dashboard runs it. PMs are known at shift start; each tool-down becomes known at its
`reported_at` (the minute its window opens), the shift is re-planned there with started work
frozen on its engineer and the usual stability charge for moving a job, and the plan that was
actually executed is scored. **Cost** here is the realised plan's operating + workload cost (the
final re-plan's stability charge is left out so it is comparable with the static cost). A shift is
re-planned 22–40 times on average (one re-plan per reveal time), each under the 0.6 s live budget;
PyVRP hit that budget in 2 of its 449 overstaffed re-plans and no other re-plan hit it. 20 seeds
per preset (`python -m scripts.benchmark --seeds 20 --only quality --mode revealed`):

| Revealed, 20 seeds | Coverage % | Bottleneck % | **Cost** | Lowest cost | Cost vs PyVRP [95% CI] |
|---|---|---|---|---|---|
| **Normal shift** (26 re-plans per shift) | | | | | |
| Greedy | 95.8 | **91.7** | 773.4 | 4/20 | +22.1 [−32.4, +84.2] |
| Hungarian | 95.7 | 86.1 | 857.9 | 2/20 | **+106.6 [+45.1, +177.0]** |
| Regret-2 | 96.2 | 90.6 | 756.1 | 6/20 | +4.8 [−27.6, +45.0] |
| ALNS | **96.5** | 89.8 | 753.6 | **7/20** | +2.3 [−33.5, +38.8] |
| PyVRP | **96.5** | 89.6 | **751.3** | **7/20** | reference |
| **Litho crunch** (31 re-plans) | | | | | |
| Greedy | 71.9 | 21.0 | 2422.0 | 3/20 | +20.5 [−20.5, +66.0] |
| Hungarian | 72.2 | **22.0** | 2428.8 | 2/20 | +27.4 [−0.7, +53.6] |
| Regret-2 | 72.4 | 21.2 | 2401.3 | 10/20 | −0.1 [−1.6, +1.8] |
| ALNS | 72.4 | **22.0** | **2401.1** | **11/20** | −0.4 [−41.6, +46.4] |
| PyVRP | **72.6** | 21.2 | 2401.5 | 7/20 | reference |
| **Excursion / surge** (40 re-plans) | | | | | |
| Greedy | 92.2 | 71.4 | 1106.2 | 7/20 | −31.2 [−66.0, +3.1] |
| Hungarian | **92.3** | **75.4** | **1102.7** | **8/20** | −34.7 [−89.0, +15.3] |
| Regret-2 | 91.7 | 71.5 | 1129.6 | 7/20 | −7.8 [−22.8, +0.0] |
| ALNS | 92.1 | 73.7 | 1104.5 | **8/20** | **−32.9 [−66.1, −5.8]** |
| PyVRP | 91.6 | 71.0 | 1137.4 | 6/20 | reference |
| **Overstaffed** (22 re-plans) | | | | | |
| Greedy | 96.1 | 93.2 | 696.9 | 6/20 | +10.6 [−24.9, +45.3] |
| Hungarian | 96.9 | 90.8 | 751.5 | 1/20 | **+65.2 [+23.6, +112.9]** |
| Regret-2 | 96.9 | 95.8 | 699.8 | 5/20 | +13.5 [−14.6, +45.8] |
| ALNS | **97.1** | **96.5** | **676.5** | **8/20** | −9.9 [−34.8, +17.3] |
| PyVRP | **97.1** | 95.0 | 686.3 | 4/20 | reference |

Without foresight the ranking mostly collapses. Seventeen of the twenty cost differences to PyVRP
have a confidence interval that includes zero. The three that don't: Hungarian is significantly
dearer on the normal shift (+106.6) and the overstaffed shift (+65.2), and ALNS is significantly
cheaper in the surge (−32.9 [−66.1, −5.8]), where its stability-aware re-planning moved fewer people
and PyVRP had the dearest realised plan of the five. Greedy is never significantly dearer than PyVRP
and had the lowest realised cost in 20 of the 80 shifts, for about 30 ms of solving per shift
against 3–4 s for ALNS and PyVRP (normal shift: 29, 33, 61, 3,071 and 4,070 ms in table order).
Idle wait all but vanishes (normal shift: 15–50 minutes, against 49–574 in the static table),
because a tool-down is only known once its window is open, so nobody can be sent early to stand at
it; that is where most of the static saving came from. Litho-crunch bottleneck coverage falls to
21–22% (36–37.5% static) for the same reason: a litho down that no certified engineer is near when
it is reported often can't be reached inside its window.

The static tables therefore measure how well a method plans a *known* shift, which is the
next-shift planning case. For live dispatch the revealed numbers are the ones that matter, and on 20
seeds they separate the methods only at the edges: avoid Hungarian, and in a surge ALNS's
re-planning helps. The two search methods spend two orders of magnitude more compute than the
one-pass rules for no measured gain in three of the four presets. Re-planning policies that keep
capacity in reserve are the obvious next experiment.

### Distance from the proven optimum

20 small shifts (4 engineers × 12 jobs) solved exactly by route enumeration plus a set-partitioning
MILP (HiGHS). Gap = (strategy cost − optimum) / optimum.

| Strategy | Mean gap | Worst gap | Found the optimum |
|---|---|---|---|
| Greedy | 6.3% | 20.7% | 5/20 |
| Hungarian | 10.9% | 56.8% | 3/20 |
| Regret-2 | 3.6% | 14.2% | 6/20 |
| **ALNS** | **0.2%** | 3.2% | **19/20** |
| PyVRP | **0.2%** | **2.5%** | 15/20 |

At this size ALNS and PyVRP are both within 0.2% of the optimum on average, and Hungarian is the
furthest from it (one shift 56.8% off). Reproduce: `python -m scripts.benchmark --only gaps`.

### Distance from the proven optimum at full size

The same exact method scales to full shifts: routes are short (4–6 jobs per engineer) and time
windows prune hard, so a 14 × 45 shift has about 42,000 feasible routes on average. Every one of the
80 shifts below was **solved to proven optimality** (HiGHS, relative gap 0). Each optimum is built
and costed by the same planner as the heuristics, and the study fails if any heuristic ever beats
it. Proof time depends on the hardware: on the laptop, with 16 proofs side by side at one HiGHS
thread each (`FAB_EXACT_THREADS=1`), a proof took about a minute on average (66.8 s) and the hardest
shift 759 s, about 13 minutes; on the 4-core container it was 203 s on average and up to 55 minutes.
The gaps themselves came out the same to the decimal on both machines. Reproduce:
`python -m scripts.benchmark --only gaps-full` (13 minutes wall clock on the laptop).

| Strategy | Mean gap | Worst gap | Mean gap on the changeable cost | Found the optimum |
|---|---|---|---|---|
| Greedy | 29.3% | 74.3% | 29.8% | 0/80 |
| Hungarian | 29.8% | 83.3% | 30.4% | 0/80 |
| Regret-2 | 20.1% | 61.4% | 20.4% | 0/80 |
| ALNS | 5.7% | 23.2% | 5.8% | 0/80 |
| **PyVRP** | **3.9%** | **11.2%** | **4.0%** | 0/80 |

| Mean gap by preset | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| Normal shift | 36.2% | 41.4% | 28.6% | 8.5% | **6.4%** |
| Litho crunch | 7.1% | 8.3% | 4.2% | **0.8%** | 1.3% |
| Litho crunch, on the changeable cost | 9.1% | 10.6% | 5.6% | **1.1%** | 1.8% |
| Excursion / surge | 33.7% | 33.7% | 18.7% | 4.6% | **2.5%** |
| Overstaffed | 40.4% | 35.6% | 28.8% | 9.1% | **5.2%** |

PyVRP is the closest to the optimum overall and in three presets, but **in the litho crunch ALNS
is closer** (0.8% vs 1.3%, 1.1% vs 1.8% on the changeable cost), which matches the quality study,
where ALNS is significantly cheaper there (−11.3 [−17.9, −5.2]). That is the strongest evidence that
ALNS earns its place next to PyVRP: when scarce certifications dominate the cost, optimising the
exact objective pays. No strategy found the optimum in any of the 80 full-size shifts.

**The litho-crunch gap is deflated by cost nobody can change.** In that preset much of the objective
is the penalty for jobs that no engineer on shift is certified for: every plan, the optimum
included, pays it, so a gap measured on the whole cost shrinks by construction. The study therefore
also prints the **gap on the changeable cost**, (strategy − optimum) / (optimum − penalty of jobs no
engineer in the instance can serve). Over all 80 shifts that penalty is 4% of the optimum on average
(56% at most), so overall the two gaps are close; in the litho crunch they are not. On the cost a
dispatcher can change, Hungarian is 10.6% off there and PyVRP 1.8%, not 8.3% and 1.3%, so the litho
crunch is not the "easy" preset the whole-cost gap suggests. In the other three presets the two gaps
are equal. The capacity-bound part of the penalty (jobs a qualified engineer exists for but can't
reach in time) is left in the changeable cost on purpose: a better plan can serve those.

**ALNS at a larger budget.** Does a much larger budget close ALNS's gap to PyVRP? At the shipped
300 iterations ALNS is 8.5% from the optimum on the normal shift (PyVRP 6.4%). With 20,000
iterations it is 1.9% on the normal shift and 1.4% over all 80 shifts (worst 4.6%), and it finds the
proven optimum on 10 of 80 shifts (8 of them in the litho crunch), against 0 for every strategy at its
shipped budget. So ALNS's gap is search budget, not a modelling limit; the shipped 300 iterations are a
latency choice (about 0.2 s at 14 × 45).
Reproduce: `python -m scripts.benchmark --only gaps-full --alns-iterations 20000`.

**Where the full proof stops scaling, and what replaces it.** Enumeration grows explosively: about
400,000 routes at 20 × 65 and 12.7 million at 30 × 100, where in an earlier run a direct MILP over
every route didn't finish its first LP in hours. Column generation replaces it: solve a small LP,
use its prices to scan *all* routes for any that could improve the plan, add those, repeat. The
converged LP is a **certified lower bound** no plan can beat; an integer solve over the generated
routes gives a real plan, and each heuristic's distance to the bound is a certified *maximum* gap to
the optimum.

At 30 × 100 (normal preset, seed 0; `python -m scripts.certified_bound 30 100 0 out/cg_30x100`) the
laptop enumerated 12.7 million routes in 261 s, column generation converged in 12 iterations (5 s,
28,914 routes generated) and the integer solve took 10 s. The optimum lies between **1002.8 and
1012.7** (the best plan is within 0.99% of the bound):

| 30 × 100, seed 0 | Cost | Gap to the optimum |
|---|---|---|
| Greedy | 1279.3 | 26.3–27.6% |
| Hungarian | 1418.6 | 40.1–41.5% |
| Regret-2 | 1281.6 | 26.5–27.8% |
| ALNS | 1139.9 | 12.6–13.7% |
| **PyVRP** | **1134.3** | **12.0–13.1%** |

The lower end of each range is the distance to the best plan found, the upper end the distance to
the certified bound. No job on this shift is uncoverable by certification, so the changeable-cost
gap is the same.

Earlier in the 2.9.0 work, 20 × 65 was bounded on three seeds on the 4-core container
(`python -m scripts.certified_bound 20 65 0 out/cg_20x65 --seeds 3`; 392,000–414,000 routes per
shift). That run predates the last PyVRP fix (keep the PyVRP solution that is cheapest by the
planner's cost) and was not repeated for this release, so read its PyVRP column as an upper bound:

| 20 × 65, seed | Lower bound | Best plan (within) | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|---|---|
| 0 | 916.5 | 921.6 (0.55%) | ≤36.7% | ≤19.0% | ≤19.5% | ≤8.3% | ≤9.9% |
| 1 | 718.6 | 726.1 (1.05%) | ≤46.9% | ≤30.6% | ≤32.8% | ≤10.7% | ≤16.1% |
| 2 | 843.2 | 852.4 (1.09%) | ≤46.1% | ≤29.5% | ≤32.2% | ≤11.0% | ≤7.7% |
| **mean of 3** | | | 43.2% | 26.4% | 28.2% | **10.0%** | 11.2% |

**The gaps grow with size.** PyVRP is 3.9% from the optimum on average at 14 × 45 (11.2% at worst
over 80 shifts), at most about 11% at 20 × 65 (three seeds, earlier build) and 12.0–13.1% at
30 × 100; ALNS goes from 5.7% to about 10% to 12.6–13.7%. The 30 × 100 reading is **one shift**
(n = 1), but it lies above the worst of the 80 full-size shifts, so it points the same way as the
three 20 × 65 seeds. The one-pass rules stay 20–40% off at every size. That is the quality argument
for decomposition (below): keep each solved problem near the size where search is a few percent from
optimal. Reproduce at any size, seed count and preset:
`python -m scripts.certified_bound 30 100 0 out/cg_30x100 --seeds 3 --preset normal`.

### Scale: 20,000 engineers, measured

A company of 20,000 engineers on three shifts has about 6,700 on shift. Fabs, skills and areas split
that into independent subproblems; the study **plans 222 independent areas** of 30 engineers × 100
jobs, each a fresh `allocate` of its own shift (it is not one re-plan of a shared plan), in parallel.
It also drives 50 tool-downs into one live 30 × 100 shift through the real live-dispatch code, spread
over the whole 720-minute shift so the number of open jobs varies as it would in practice, and solves
three undecomposed problems. Reproduce: `python -m scripts.scale_study out/company`.

Measured on the laptop, 16 workers, 3 s solver safety cap:

| What | Measured |
|---|---|
| Plan **222 independent areas** (6,660 engineers, 22,200 jobs, PyVRP, 16 workers) | **14.6 s** wall clock, 223 CPU-s; 0.99 s per area (p95 1.17 s); every area ran its full 1,000 iterations, **0/222 hit the 3 s cap** (so no capped-vs-uncapped comparison was needed; the script runs one when any area is capped) |
| **Live tool-down** re-planned through the real live-dispatch code (50 events at clocks 7–713 of 720, 7–53 open jobs at the event, ALNS) | **p50 83 ms, p95 159 ms**, max 163 ms; 0/50 hit the 0.6 s live cap |
| Tool-down rate implied by the generated company | 12,312 tool-downs across the 222 shifts = **0.29 per second** over the 720-minute shift |

At 0.29 tool-downs per second and 83 ms per re-plan, live re-planning needs about 2.4% of one core
(one core serves about 12 re-plans a second at the median). The same work *without* decomposition,
as one problem (one seed; `warm` is the regret-2 warm start both search methods pay before their
3 s search budget starts):

| One problem | Regret-2 | ALNS | PyVRP |
|---|---|---|---|
| 100 × 300 | 0.9 s, cost 3,299 | 4.0 s (0.9 warm + 3.0 search, 62 iterations, capped), cost **3,260** | 3.2 s (0.9 warm + 2.3 search, 1,000 iterations, not capped), cost 3,299 |
| 150 × 500 | 4.1 s, cost 6,075 | 7.7 s (4.2 warm + 3.3 search, 26 iterations, capped), cost 6,048 | 7.7 s (4.2 warm + 3.1 search, 849 iterations, capped), cost **6,040** |
| 300 × 1,000 | 51 s, cost 11,841 | 71 s (52 warm + 18 search, **5 iterations**, capped), cost 11,841 | 63 s (52 warm + 4 search, 500 iterations, capped), cost 11,841 |

Two findings. **Decomposition is required, not optional**: one 300 × 1,000 problem takes a minute
and neither search method improves on its warm start, while 222 areas of 30 × 100 plan in 15 s with
every area getting its full budget. **At size, a 3 s search buys about 1% at most.** ALNS runs 62
iterations at 100 × 300 and ends 1.2% below regret-2; PyVRP finishes its 1,000 iterations there
without improving on the warm start. At 150 × 500 both end 0.4–0.6% below regret-2, and at
300 × 1,000 neither changes it: one destroy-and-repair of a 1,000-job plan takes seconds, and the
3 s cap is checked between iterations, which is why ALNS's search ran 18 s. These are single runs
on one seed.

### Bigger shifts locally: 100 × 100 to 1,000 × 1,000

The hosted demo caps a shift at 60 engineers × 200 jobs so one request fits Vercel's 60 s function
limit. Locally the cap is configuration, not code: start the API with
`FAB_MAX_ENGINEERS=1000 FAB_MAX_JOBS=1000` and the UI reads the new limit from `/api/meta`. This is
what the shipped settings (3 s search cap, 300 ALNS and 1,000 PyVRP iterations) do at three sizes,
one seed each, measured with the 2.9.0 code on a 4-core Linux container (Intel Xeon @ 2.1 GHz,
15 GB of memory; cost is the objective, lower is better; `warm` is the regret-2 warm start both search methods build before their budget starts):

| Engineers × jobs | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| 100 × 100 | 0.05 s, cost 658 | 0.4 s, 743 | 0.3 s, 623 | 3.3 s (0.3 warm, 222 iterations, capped), **597** | 3.5 s (1,000 iterations, not capped), 623; 300 MB |
| 300 × 300 | 0.5 s, 1,322 | 1.5 s, 1,644 | 8.6 s, 1,278 | 11.7 s (8.1 warm, **8 iterations**, capped), 1,276 | 27 s (8.6 warm, 187 iterations, capped), 1,278; **4.8 GB** |
| 1,000 × 1,000 | 6.0 s, 5,627 | 34 s, 6,975 | **476 s**, 5,581 | 669 s (460 warm, **4 iterations**), 5,574 | **killed by the 15 GB memory limit** after 57 s |

Coverage is the same for every strategy at a given size (99.0%, 99.7%, 98.6%): which jobs go
unserved is decided by skills and shift capacity, not by the strategy. The strategies differ in
cost, and the ranking holds at every size: ALNS ≤ regret-2 ≈ PyVRP < greedy < Hungarian.

Through the API on the same container, the 1,000 × 1,000 scenario generates in 0.1 s (339 kB of
JSON), a greedy `/plan` answers in 6.2 s (722 kB) and Hungarian in 36 s, and a live shift of that
size starts normally. **In the UI, Generate fires all five `/plan` requests at once** (fast ones
render first), and at 1,000 × 1,000 that is the problem: PyVRP's request grows the API process
until the kernel kills it at 13.8 GB, which also drops the regret-2 and ALNS requests running in
the same process, so the UI reports those three strategies as failed and recommends from the two
it has. There is no UI switch to leave a strategy out, by design (the comparison is the point), so
for undecomposed shifts above about 500 × 500 call `/plan` with one strategy per request. The floor plan itself
copes: it is an SVG with one element per job and engineer, and it draws the greedy plan's 1,000
jobs and 1,000 engineers 0.7 s after "View on floor plan" (measured in headless Chromium). What
does not scale is the floor: it stays 400 × 240 m whatever the headcount, so at 2,000 markers they
overlap and a job cannot reliably be picked by clicking (an engineer's marker sits on top of it).
A real floor of that size would be drawn per area, which is the same decomposition as above.

What the numbers say:

1. **Greedy and Hungarian are the only strategies that stay interactive at 1,000 × 1,000** (6 s
   and 34 s). Hungarian's rounds are cubic in the number of engineers, which is why it falls
   behind greedy from 300 × 300 on.
2. **Regret-2, not the metaheuristics, is the bottleneck.** It is pure Python and re-scores every
   open job against every engineer's route after each insertion, so its time grows a little faster
   than the cube of the size: 0.3 s → 8.6 s → 476 s. ALNS and PyVRP both pay it as a warm start,
   so at 1,000 × 1,000 "ALNS" is regret-2 plus four destroy-and-repair iterations of about 50 s
   each (the 3 s cap is checked between iterations, which is why it overshoots so far), and its
   plan is 0.1% below the warm start.
3. **PyVRP's memory is the hard wall on a small machine.** It builds one distance and one duration matrix per
   engineer over every job, so memory grows as engineers × jobs²: 300 MB at 100 × 100, 4.8 GB at
   300 × 300, and 1,000 × 1,000 extrapolates to over 100 GB. The process was killed while building
   them. The fix is not more memory: it is one matrix shared by every engineer (the walking
   distances are the same, only the skills differ), which pyvrp's profile API supports and which
   this project has not done because no real shift needs it (next point).
4. **A 1,000 × 1,000 shift is not a real planning unit.** A fab with 1,000 engineers on shift has
   them in 30–60 areas with their own tools and skills; the company study above plans 222 areas
   of 30 × 100 (6,660 engineers) in 15 s on the laptop with every area getting its full iteration
   budget.
   Decomposing by area is the answer to "1,000 × 1,000", and the limit is configurable so that
   reviewers can confirm the undecomposed numbers for themselves rather than take this on trust.

If you do want to run the undecomposed problem: raise `FAB_SOLVER_TIME_LIMIT_S` (ALNS then gets
more than four iterations; PyVRP at 300 × 300 was at 187 of its 1,000 iterations when the cap
hit), and keep PyVRP out of the strategy list above about 500 × 500 unless the machine has the
memory. Reproduce one cell, from `backend/` with the virtualenv active:

```bash
python -c "
import time; from app.generator import generate; from app.engine import allocate; from app.models import Weights
sc = generate(0, 1000, 1000, 'normal'); t = time.perf_counter(); r = allocate(sc, Weights(), 'greedy')
print(round(time.perf_counter() - t, 1), 's; cost', r.metrics['objective'], r.solver)"
```

### Solve time (ms, one shift)

Median of 5 runs per cell on the laptop (Apple silicon, 18 cores, Python 3.14.7; this is what
`python -m scripts.benchmark --only scaling` prints the platform for):

| Size | Greedy | Hungarian | Regret-2 | ALNS | PyVRP |
|---|---|---|---|---|---|
| 14 engineers, 45 jobs | 2 | 4 | 7 | 176 | 337 |
| 30 engineers, 100 jobs | 8 | 14 | 38 | 757 | 612 |
| 60 engineers, 200 jobs | 27 | 64 | 242 | 3,296* | 1,600 |

\* Hit the 3 s safety cap before the iteration budget. Those plans are still good but not
reproducible, so they're kept out of the shared cache (see [DECISIONS.md](DECISIONS.md) D5). Timing
depends on the hardware: a 4-core container or Vercel's serverless CPU is several times slower than
this laptop.

### Sizing the search budget

How much quality each extra iteration buys (12 shifts, cost reduction relative to regret-2). The
shipped budgets, 300 ALNS and 1,000 PyVRP iterations, are **not equal wall time**: the last row
gives ALNS the iteration count that fits in PyVRP's shipped solve time on the same machine, which
is the fair comparison. The ALNS budget is a real budget: its time limit starts after the regret-2
warm start, as PyVRP's does, and its temperature cools to 0.1% of its start by the last iteration
whatever the budget.

Measured on the laptop (`python -m scripts.benchmark --only budgets`):

| Solver | Iterations | Cost below regret-2 | Mean solve ms |
|---|---|---|---|
| ALNS | 100 | 9.3% | 52 |
| ALNS | **300** (shipped) | 13.0% | 152 |
| ALNS | 600 | 13.1% | 297 |
| PyVRP | 250 | 13.2% | 80 |
| PyVRP | **1000** (shipped) | 13.8% | 294 |
| PyVRP | 3000 | 14.3% | 891 |
| ALNS | 580 (= PyVRP 1000's wall time) | 13.7% | 294 |

The curves flatten fast: doubling ALNS to 600 iterations adds 0.1 points, tripling PyVRP to 3,000
adds 0.5. At equal wall time the two solvers are 0.1 points apart (13.7% vs 13.8% below regret-2),
so the shipped budgets, which give PyVRP about twice ALNS's time, understate ALNS by about 0.7
points. The shipped budgets sit at the knee of both curves.

Going from 1,000 to 3,000 PyVRP iterations triples latency (on serverless, from about 1 s to past
the 3 s cap). Teams that value cost over latency can raise the budgets with
`FAB_PYVRP_ITERATIONS` / `FAB_ALNS_ITERATIONS`; the plan cache keys on the budget, so the change
is safe.

### Industrial AI: durations, failure predictions, a learned policy

Three studies on the questions a predictive-maintenance team asks first. All data is synthetic
(generated from each fab's fault catalogue with fixed seeds), so the numbers measure the method,
not a real fab. Each reproduces in seconds to minutes with the command shown.

**1. How good are the repair-time estimates?** Trained on each fab's 1,800-repair history and
tested on 600 repairs it never saw (`python -m scripts.duration_study out/durations`). A P10–P90
range is calibrated when 80% of repairs fall inside it, a P90 when 90% finish by it:

| Estimate (fab 1; fab 2 is 2–4 min lower) | MAE (min) | Repairs over the estimate | P90 coverage | P10–P90 coverage |
|---|---|---|---|---|
| Standard estimate per fault code (today's default) | 34.7 | 46% | n/a | n/a |
| Fault-code mean from history | 34.6 | 49% | 86.0% | 74.8% |
| **k-NN over repair history (the app's retrieval)** | **26.7** | 48% | **88.3%** | **79.7%** |
| Cause classifier (logistic regression on the symptom's words) | 24.9 | 49% | 88.0% | 76.7% |
| Quantile gradient boosting (P10/P50/P90) | 25.7 | 49% | 80.8% | 63.0% |
| Oracle that knows the root cause | 17.0 | 49% | 88.7% | 76.7% |

The history-based estimates now beat the standard estimate: k-NN is 8 minutes closer on average
(26.7 vs 34.7 on fab 1, 23.0 vs 32.4 on fab 2). The reason is the symptom text. Each fault code has
root causes with different repair times (the spread within a code is about 38 minutes), and 61% of
the test symptoms carry an observation that points to the cause. When one does, k-NN names the true
cause 96.5% of the time and its error falls to 20.2 minutes; when none does, it names it 48.5% of
the time (chance is 50%) and its error is 37.0 minutes, no better than the lookup table. So the gain
is as large as the share of symptoms that describe the cause, and that share is a generator setting:
a fab whose technicians write vaguer notes would see less of it. In 2.8.0 no symptom carried such an
observation, which is why no model beat the standard estimate then. The other half of the value is
the **range**: k-NN's P10–P90 holds 79.7% of repairs and its P90 88.3%, close to calibrated, so a
planner can protect bottleneck tools with P90 instead of the mean. The boosted trees' ranges are
too narrow (63% inside P10–P90). Getting from 27 minutes towards the oracle's 17 needs a cause
signal for the symptoms that don't carry one (sensor data, alarm codes, time since last PM), not a
better regressor.

**2. Does planning on failure predictions pay?** Each tool-down is a failure at a known minute. A
mock predictor flags a share of them (recall) some minutes ahead (lead time) and raises false
alarms (precision), each a 45-minute inspection that finds nothing. Flagged failures enter the live
plan at prediction time; a repair started before the failure means no unplanned downtime, but it
still takes the tool offline while it runs. So the study reports two numbers: unplanned downtime
saved, and the **net availability gain** (unplanned downtime + planned repair + inspection minutes,
against reactive dispatch). 40 normal shifts (14 × 45, regret-2) replayed through the real
live-dispatch code, paired against reactive dispatch, bootstrap 95% CIs
(`python -m scripts.predictive_study out/predictive`):

| Predictor (recall 60%, lead 90 min, precision 70%, planned repair as long as a breakdown, unless stated) | Unplanned downtime saved per shift | Net availability gain per shift | Failures prevented |
|---|---|---|---|
| Reactive (today) | baseline: 3,418 min | baseline | 0% |
| Recall 30% | 600 min (490 to 723) | −75 min (−159 to +10) | 21% |
| Recall 60% | 1,209 min (1,088 to 1,340) | **−127 min (−209 to −38)** | 41% |
| Recall 90% | 1,882 min (1,717 to 2,046) | −100 min (−175 to −25) | 61% |
| Lead 30 min | 827 min | −319 min (−408 to −235) | 33% |
| Lead 60 min | 1,072 min | −158 min (−226 to −86) | 37% |
| Lead 120 min | 1,364 min | −47 min (−143 to +55) | 44% |
| Precision 40% | 890 min | −1,013 min (−1,112 to −907) | 38% |
| Precision 100% | 1,335 min | **+267 min (+190 to +348)** | 42% |
| Planned repair at 70% of breakdown time | 1,366 min | **+321 min (+236 to +411)** | 42% |
| Planned repair at 50% of breakdown time | 1,367 min | **+515 min (+395 to +641)** | 43% |

Prediction cuts unplanned downtime in every scenario, and more recall and more lead cut it more.
On its own that is not a gain in availability: a repair done before the failure takes as long as one
done after it, and every false alarm adds an inspection. At 60% recall and 70% precision with equal
repair times the tools are unavailable **127 minutes longer** per shift than with reactive dispatch,
and at 40% precision about a thousand minutes longer. Net availability only improves when planned
repair is shorter than breakdown repair (+321 minutes at 70% of the time, +515 at 50%: parts and
procedure ready) or when there are no false alarms (+267 at 100% precision). On bottleneck tools the
net gain is significant only in those same three scenarios (+58 to +112 minutes). So the case for
predictive maintenance here rests on precision and on planned repairs being shorter, not on recall
alone. The mock predictor's errors are random; a real one's would be correlated with tool age and
load.

**3. Can a learned dispatch policy compete?** Greedy dispatch with a learned job order: each job
is scored on six features (priority, window start, window end, duration, certification level, and
scarcity = how few engineers can do it), and the weights are learned by the cross-entropy method, a
gradient-free policy-search form of reinforcement learning, on 40 training shifts (the shift
generator is the environment, reward = minus plan cost). The search is repeated from 5 seeds, and
each learned order is tested on 40 unseen shifts (10 per preset) against their proven optima
(`python -m scripts.learned_policy_study out/learned`):

| Strategy | Mean gap to optimum | Worst gap |
|---|---|---|
| Greedy, hand-written order | 29.4% | 66.8% |
| **Greedy, learned order** (5 seeds) | **26.3%** (sd 1.6, range 24.1–28.0) | 59.0–69.8% |
| Regret-2 | 18.9% | 37.2% |
| ALNS | 5.9% | 23.2% |
| PyVRP | 3.8% | 11.2% |

Learning the order is worth a few points at best, and not reliably. The seed with the best training
cost gains 4.1 gap points over the hand-written rule (95% CI 0.3 to 7.8); the median seed gains 1.4
(CI −3.1 to 6.1, not significant), and the worst case is no better. The 7-point gain reported in
2.8.0 came from a single search seed. A learned *order* still commits each job once, so it stays far
from regret-2 and further from the search methods: the remaining gap comes from revisiting
decisions, which search does. The proven optimum is what makes this a fair test; a learned policy
scored only against other heuristics could look better than it is. The useful role for learning
here is inside search (learning which ALNS moves to try), not replacing it.


## 2. What I learned

**1. With a known shift, search beats any one-pass rule; without foresight it mostly doesn't.** In
the static benchmark regret-2 reached the lowest cost in one litho-crunch shift and PyVRP or ALNS
did in every other one, and the one-pass rules are significantly more expensive than PyVRP in every
preset (regret-2, the best of them, by +57 to +140 points, every interval clear of zero). Most of
that saving is **idle wait**: regret-2 leaves engineers standing at tools for windows to open for
93–543 minutes a shift, PyVRP for 16–247, because only re-sequencing whole routes removes that
waiting. But the static benchmark hands every method the tool-downs before they happen. Replayed
through the live code with jobs revealed at `reported_at` (20 seeds), 17 of the 20 cost differences
to PyVRP are not significant, greedy is never significantly dearer and had the cheapest realised
plan in 20 of 80 shifts, and idle wait all but disappears. The static result is the next-shift
planning case; for live dispatch the cheap rules did as well as search, Hungarian excepted.

**2. Small test cases flatter heuristics, and only a full-size proof shows it.** On 4 × 12 shifts
ALNS and PyVRP are both within 0.2% of the optimum and the one-pass rules 4–11% off. At full size,
proven optimal on 80 shifts, PyVRP is 3.9% from the optimum, ALNS 5.7% and the one-pass rules
20–30%; at 30 × 100 (one shift) both search methods are 12–14% off. ALNS optimises our objective
exactly, including the convex workload-balance term that PyVRP can't express: it is tied with PyVRP
on the normal shift, closer to the optimum and significantly cheaper in the litho crunch, and 19–21
points behind on the surge and the overstaffed shift. The lesson stands: measure against a proven
optimum at the size you'll actually run, not a size that's convenient to prove.

**3. Hungarian is the fairest method and the fastest to respond, for one reason.** Hungarian has by
far the most even workload (std 0.5–0.9 vs 1.0–1.5) and the fastest response in every preset
(7.4–31.2 min). Each round gives every engineer at most one job, chosen optimally for that round, so
work spreads out and everyone's first job starts promptly. But a round is optimal only for itself:
later jobs get slotted where engineers wait for windows, so its idle wait is the highest of all
five in every preset (388–1,232 minutes). With tool-downs revealed as they happen it is the one
method significantly dearer than PyVRP, on the normal (+107) and overstaffed (+65) shifts. If the
fab's top KPI is fairness or time-to-respond, Hungarian is a defensible choice, at a cost.

**4. Greedy fails predictably, by spending scarce engineers too early.** `test_greedy_falls_into_the_trap`
is the minimal case: the critical job takes the nearest engineer, who was the only one able to reach a
second, tighter tool-down. Regret-2 exists to prevent exactly this ("place the job with the fewest good
options first"). It beats greedy on cost in every static preset (by 45 to 134 points). With
tool-downs revealed as they happen the two are not separable.

**5. When certifications run out, no algorithm helps.** In litho crunch, all five hit the same ceiling:
73–74% coverage and 36–37.5% of bottleneck downs. The best search covers about one point more than
greedy, and much of the remaining cost is the penalty for jobs nobody on shift can take (see "gap on
the changeable cost" above). The Workforce view and the unassigned reasons ("no engineer on shift
holds litho level 3+") point to the real fix: cross-training or staffing. For a fab manager, that's
often the most valuable output.

## 3. When does each approach win? (the brief's question)

| Situation | Best choice | Why |
|---|---|---|
| A job must be dispatched **the instant** it arrives; no batching window | Greedy, or regret insertion into the current plan | Milliseconds, explainable in one sentence. In the revealed-information replay (20 seeds per preset) greedy was never significantly dearer than PyVRP and had the lowest realised cost in 20 of 80 shifts, for about 30 ms of solving per shift against 3–4 s. |
| **Contention**: many jobs competing for few qualified engineers, tight windows | Regret-2 at minimum, a search method ideally | One-at-a-time commitment strands jobs; in the surge, with the shift known, greedy is 274 points (30%) dearer than PyVRP. |
| KPI is **fairness** and time-to-respond | Hungarian in rounds | Most even workload and fastest response in every preset. Accept the idle-time cost: with tool-downs revealed as they happen it is still significantly dearer than PyVRP on two of four presets. |
| KPI is **total cost or throughput** for a shift planned ahead, and a fraction of a second is acceptable | PyVRP or ALNS | Lowest static cost in 50/80 (PyVRP) and 31/80 (ALNS) shifts; one-pass rules are significantly dearer in every preset. PyVRP is significantly cheaper on the surge and overstaffed shifts; on the normal shift the two are tied (+11.3 [−2.1, +27.3]). |
| The objective has terms a library can't express (balance, stability, custom penalties), or scarce certifications dominate | ALNS | Optimises the exact objective; in the litho crunch it is closer to the optimum than PyVRP (0.8% vs 1.3%) and significantly cheaper (−11.3), and live it is significantly cheaper in the surge (−32.9). |
| The plan is made **ahead of time** (next shift) and minutes are acceptable | Exact (set partitioning) | Proven optimal: 3.9% cheaper than PyVRP on average, up to 11%. About a minute per proof on average at 14 × 45, the hardest shift about 13 minutes on a laptop (timing depends on the hardware); at 30 × 100 only column generation's certified bound is practical. |
| **Plenty of engineers** (overstaffed) | Any for bottleneck work; search for the rest | All five cover 100% of bottleneck downs. Greedy still drops PMs (93.5% vs 98.8% overall coverage) and costs 33% more than PyVRP. |
| **Certification shortage** | Fix staffing | All strategies hit the same ceiling (73–74% coverage). |

**When does the difference matter most?** Where engineers are contended and the shift is known
ahead. With slack engineers and wide windows, bottleneck work gets done whatever the method, and the
differences are cost and PMs. With scarce skills and tight windows (the surge), the order of
decisions starts to decide *whether* urgent work gets done (88.5% → 90.4% of bottleneck downs) and
the cost spread is widest (greedy 30% dearer than PyVRP). At hard capacity limits the gap closes
again, because nothing can be done (litho crunch: 36–37.5% of bottleneck downs for every method).
Between the two search methods it matters least: they are tied on the normal shift and 1–3% apart
elsewhere. And when tool-downs are only known as they happen, most differences fall inside the noise
of 20 seeds; what still matters is avoiding Hungarian on the normal and overstaffed shifts and, in a
surge, re-planning with ALNS.

## 4. Why these algorithms, and not the newest ones in the literature?

I checked the current research (October 2026) before settling the lineup. Short answer: the lineup
contains the state of the art for the *routing core* of this problem (the VRPTW), I measured the
headroom above it exactly instead of guessing (3.9% on average at 14 × 45), and the open research
frontier is somewhere else (uncertainty, not search). One honest caveat up front: the problem class
here is the technician routing and scheduling problem (TRSP), also studied as workforce scheduling
and routing (WSRP), and none of these strategies was run on a published TRSP instance set. The
benchmarks that back the "state of the art" label are VRPTW benchmarks, so the label covers the
routing engine, not the whole problem.

**The lineup spans every family, and its best member is the strongest open-source VRPTW engine.**

| Family | Here | Why it's in |
|---|---|---|
| Construction | Greedy, Regret-2 | What dispatchers do by hand; the baseline every method must beat |
| Assignment | Hungarian | Optimal one-job-per-round matching; best response time and fairness |
| Large neighbourhood search | ALNS | Optimises *our* exact objective; the family that recent LLM-designed operators improve ([VRPAgent](https://arxiv.org/pdf/2510.07073)) |
| Iterated local search | PyVRP | The pinned `pyvrp==0.14.0` ships iterated local search (ILS) only, with no population or genetic module. The competition wins belong to the hybrid genetic search (HGS) described in the [2024 PyVRP paper](https://arxiv.org/abs/2403.13795): first in the [2021 DIMACS VRPTW challenge](http://dimacs.rutgers.edu/programs/challenge/vrp/vrptw/) and in the static track of the [EURO meets NeurIPS 2022 competition](https://github.com/ortec/euro-neurips-vrp-2022-quickstart). The ILS is built on the same library's C++ local search and is what `pyvrp.solve` runs in this release |
| Exact | Set-partitioning MILP | Proves the optimum at full size, so every gap is measured, not guessed |

**The headroom is measured, and it's modest at the size dispatch runs.** At full size, proven
optimal on 80 shifts, the best heuristic (PyVRP) is 3.9% from the optimum on average and 11.2% at
worst (section 1). That is the most any new solver could gain on a 14 × 45 shift, and the exact
method already captures it when there's time to plan ahead. The headroom grows with size (12–13% at
30 × 100, one shift), which is one more reason to decompose. So the open question isn't "which
newer heuristic?", it's how to get the optimum *fast enough for live dispatch*: column generation
(pricing routes instead of enumerating all of them) is the established way to do that, and it's the
next step for the solver.

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
  hard `max_jobs` cap this lets even the *proven optimum* abandon a bottleneck down that no
  certified engineer can reach inside its window, and the model has no way to prefer "late" over
  "never".
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
  at 60 × 200 on the laptop and gets 62 iterations at 100 × 300). PyVRP, or a compiled ALNS, would be
  the path.
- **No external benchmark.** Every gap here is measured on this generator's shifts. Running the
  strategies on a published technician routing and scheduling instance set (section 4) would show
  where they stand against that literature, not only against each other.
