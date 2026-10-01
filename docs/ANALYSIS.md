# Algorithm comparison

Generated with `python -m scripts.benchmark --seeds 30`: 30 seeded shifts per preset, 14 engineers,
45 jobs, default weights. "Best objective" counts the seeds where an algorithm had the lowest total
cost (ties count for all).

| Preset | Algorithm | Coverage % | Bottleneck downs % | Response to downs (min) | Walk m/job | Idle wait (min) | Load std | Objective ↓ | Best objective |
|---|---|---|---|---|---|---|---|---|---|
| Normal | greedy | 95.6 | 100.0 | 20.9 | 103.9 | 2165 | 1.8 | 889 | 3/30 |
| | hungarian | **99.0** | 100.0 | **14.2** | **90.2** | 2611 | **0.5** | 897 | 2/30 |
| | regret | 98.0 | 100.0 | 21.0 | 97.6 | **1724** | 1.9 | **741** | **25/30** |
| Litho crunch | greedy | 72.3 | 58.9 | 19.0 | 104.2 | 1807 | 2.1 | 2212 | 7/30 |
| | hungarian | **73.4** | **60.4** | **7.2** | **87.5** | 3301 | **1.0** | 2463 | 0/30 |
| | regret | 73.2 | **60.4** | 18.1 | 99.0 | **1564** | 2.1 | **2116** | **23/30** |
| Excursion | greedy | 96.5 | 97.2 | 8.7 | 107.0 | 2597 | 2.0 | 1063 | 8/30 |
| | hungarian | **98.8** | **99.3** | **4.0** | **91.3** | 3755 | **0.6** | 1173 | 3/30 |
| | regret | 97.4 | 97.5 | 7.5 | 99.9 | **2383** | 1.9 | **964** | **19/30** |
| Overstaffed | greedy | 95.3 | 100.0 | 27.9 | 103.3 | 2268 | 1.8 | 920 | 2/30 |
| | hungarian | **99.1** | 100.0 | **20.4** | **93.1** | 2414 | **0.5** | 857 | 1/30 |
| | regret | 97.7 | 100.0 | 27.0 | 97.6 | **1709** | 1.8 | **741** | **27/30** |

Runtime (one shift, ms):

| Size | Greedy | Hungarian | Regret |
|---|---|---|---|
| 14 engineers, 45 jobs | 1.6 | 3.3 | 7.1 |
| 30 engineers, 100 jobs | 4.6 | 15.9 | 42.6 |
| 60 engineers, 200 jobs | 17.1 | 68.1 | 284.3 |

## What I learned

**1. "Best" depends on what the fab is optimising for, and the three algorithms win on different metrics.**
Hungarian has the best coverage, the fastest response to tool-downs and the most even workload
in every preset. Regret has the lowest total cost in 19–27 of 30 seeds. Greedy is never best on
outcomes, only on speed. If the fab's KPI is getting bottleneck tools back up quickly (lost wafer
moves on a scanner cost far more than an engineer's idle time), Hungarian is the right call. If
the KPI is engineer efficiency, regret is.

**2. Hungarian's strength and weakness come from the same thing: the rounds.**
Each round gives every engineer at most one job, chosen optimally for that round. That
naturally spreads work out (load std 0.5 vs 1.8) and gets each engineer's first job started
almost immediately, which is why response time halves in the excursion preset (4.0 vs 8.7 min). But
the matching is only optimal *within* a round. Round 1 doesn't know what round 2 needs, so later
jobs get slotted into routes where they wait for windows. Idle wait is 20–110% higher than the other two, and that
is what loses Hungarian the objective. A per-round optimum is not a whole-shift optimum.

**3. Greedy fails in a predictable way: it gives away scarce engineers too early.**
The test `test_greedy_falls_into_the_trap` is the smallest version of this. The critical job goes
to the nearest engineer, who was the only one who could reach a second, tighter tool-down. Both
batch views (Hungarian's matrix and regret's "only one engineer can do this") avoid it. Across
the benchmark this costs greedy 2–4 points of coverage. Greedy is still the right tool when jobs
have to be dispatched **the moment they arrive** and can't be batched, or when engineers are so
plentiful that there is no contention.

**4. When the hard constraint is a shortage of certified engineers, the algorithm barely matters.**
In the litho-crunch preset all three algorithms hit the same ceiling: around 73% coverage and
60% of bottleneck downs. No allocation strategy can create a level-3 litho engineer who isn't on
shift. The unassigned-reason report says exactly this ("No engineer on shift holds litho level 3+").
That is a staffing and cross-training decision, not an optimisation one, and it may be the most
useful output for a fab manager.

**5. The difference matters most under contention combined with tight windows.**
In the overstaffed preset every algorithm gets the critical work done. The gaps widen as SLAs
tighten (excursion) and as skills become scarce. That is where a batch view has room to find
better combinations than one-at-a-time decisions.

**6. Speed is not the constraint at fab scale.**
Even regret, the slowest, solves a 60-engineer, 200-job shift in about 0.3 s, so it can be
re-run every time a tool goes down. The cost of regret (roughly J²) would matter at
thousands of jobs, not in a single fab shift.

## Limitations and next steps

- **Online re-dispatch.** Tool-downs arrive during the shift. The natural extension is a rolling horizon: freeze in-progress jobs, then re-run regret or Hungarian over the open ones each time an event arrives. Greedy becomes the fallback when an answer is needed instantly.
- **Hybrid.** Use regret to build routes, then a local-search pass (relocate/swap between engineers) to cut idle wait. Or give Hungarian a look-ahead term so it stops creating waits.
- **An exact baseline.** OR-Tools CP-SAT or a VRPTW solver would show how far each heuristic is from optimal on small instances.
- **Real priority.** Instead of a fixed 1–3, cost a tool-down by the WIP queued behind that tool and whether it is the current constraint (both available from the MES).
- **Uncertainty and ML.** Repair durations are really distributions. Learning them per tool and failure code from maintenance history, then planning with buffers, would make the schedule more robust.
- **Two-person jobs** (some PMs and safety-critical work) and parts availability are not modelled yet.
