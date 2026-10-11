"""Does planning on failure predictions beat reacting to breakdowns? A mock predictive-maintenance feed.

    python -m scripts.predictive_study out/predictive           # writes .log and .json
    python -m scripts.predictive_study out/predictive --quick   # 4 shifts, 3 scenarios, smoke test

Every tool-down in a generated shift is a failure at a known minute (its window start). Reactive
dispatch (today) learns of it when it happens. A predictor flags a share of failures (recall) some
minutes ahead (lead time); a flagged failure enters the live plan as a job at prediction time, so
an engineer can repair it before the tool goes down. The warning only moves the window's start
earlier: the latest start stays the failure time + the job's SLA, as without a prediction, so a
prediction gives the dispatcher more time, never a later deadline.

Predictors also raise false alarms (precision). Each is drawn like a real flagged failure, so the
dispatcher cannot tell them apart by priority or window: a random real tool-down is copied (tool,
family, level and priority), a phantom failure minute is drawn the way the generator draws
tool-downs, and the window is built the same way (prediction lead before it, the copied job's SLA
after it). Serving one is a 45-minute inspection that finds nothing: it still costs engineer time,
and the tool is offline while it is inspected. The plan books those 45 minutes; a dispatcher would
book the expected repair, so false alarms here crowd out real work a little less than in practice.

The shift is replayed through the real live-dispatch code (app/live.py: re-plan at every event,
started work frozen). Measured per shift, within the shift:

* unplanned downtime: minutes from a failure until its repair finishes (an unrepaired failure
  counts until shift end). A failure whose repair started before it happened has none.
* tool-unavailable minutes: unplanned downtime + planned repair minutes (a repair started before
  the failure still takes the tool offline while it runs) + inspection minutes of served false
  alarms. The saving here is the net availability gain.

Both are also reported for bottleneck tools (priority 3). Everything is cut at shift end: a failure
still unrepaired then keeps its tool down into the next shift, which is not counted, so late
failures flatter reactive dispatch. Shifts are paired across scenarios (same seed and failures),
with a paired bootstrap 95% CI on every saving against reactive dispatch.
"""

import argparse
import json
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor

# One thread per worker: BLAS and solvers otherwise each spawn a thread per core under the pool.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

OUT = "out/predictive"
E, J = 14, 45  # shift size; --engineers / --jobs exist for the smoke test
ALGO = "regret"  # live re-plans run at every event; regret-2 keeps 40 shifts x 9 scenarios in minutes
INSPECTION_MIN = 45


class _Inline:
    """``--workers 1``: run in this process instead of forking one worker. The smoke test runs the
    study under pytest, where a fork after the solvers' threads have started can hang."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def map(self, fn, iterable, chunksize=None):
        return list(map(fn, iterable))


def _pool(workers, **kwargs):
    return ProcessPoolExecutor(max_workers=workers, **kwargs) if workers > 1 else _Inline()


SCENARIOS = [  # name, recall, precision, lead minutes
    ("reactive", 0.0, 1.0, 0),
    ("recall 30%", 0.3, 0.7, 90),
    ("recall 60%", 0.6, 0.7, 90),
    ("recall 90%", 0.9, 0.7, 90),
    ("lead 30 min", 0.6, 0.7, 30),
    ("lead 60 min", 0.6, 0.7, 60),
    ("lead 120 min", 0.6, 0.7, 120),
    ("precision 40%", 0.6, 0.4, 90),
    ("precision 100%", 0.6, 1.0, 90),
]
QUICK = ["reactive", "recall 60%", "precision 40%"]
METRICS = [  # per-shift totals; the savings are reported for these
    "unplanned",
    "unavailable",
    "bottleneck_unplanned",
    "bottleneck_unavailable",
]


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def run(args):
    seed, recall, precision, lead, e, j = args
    from app import live
    from app.fabs import get_profile
    from app.generator import generate
    from app.models import Weights

    sc = generate(seed, e, j, "normal")
    rng = random.Random(1000 + seed)  # the same failures are flagged across lead/precision sweeps
    fails = {j.id: j.earliest for j in sc.jobs if j.kind == "down"}
    jobs, flagged = [], 0
    for j in sc.jobs:
        if j.kind == "down" and rng.random() < recall:
            flagged += 1
            # Only the start moves: latest stays failure time + SLA.
            jobs.append(j.model_copy(update={"earliest": max(0, j.earliest - lead)}))
        else:
            jobs.append(j)

    # False alarms, indistinguishable from flagged failures by priority and window.
    n_false = round(flagged * (1 - precision) / precision) if flagged else 0
    downs = [j for j in sc.jobs if j.kind == "down"]
    fa_rng = random.Random(2000 + seed)  # the same phantom failures across sweeps
    shift_len = get_profile(sc.fab_id).shift.length_min
    false_ids = set()
    for i in range(n_false):
        src = fa_rng.choice(downs)
        t_phantom = fa_rng.randint(0, max(0, shift_len - 120))  # as the generator draws tool-downs
        sla = src.latest - src.earliest
        fid = f"F{i:03d}"
        false_ids.add(fid)
        jobs.append(
            src.model_copy(
                update={
                    "id": fid,
                    "earliest": max(0, t_phantom - lead),
                    "latest": t_phantom + sla,
                    "duration": INSPECTION_MIN,
                }
            )
        )
    sc = sc.model_copy(update={"jobs": jobs})

    state, _ = live.start(sc, Weights(), ALGO)
    live.advance(state, state.shift_length)
    times = {s.job_id: (s.start, s.end) for r in state.plan.routes for s in r.stops}
    shift = state.shift_length
    out = dict.fromkeys(METRICS, 0.0) | {"planned_repair": 0.0, "inspection": 0.0, "prevented": 0, "served_false": 0}
    for j in sc.jobs:
        start, finish = times.get(j.id, (None, None))
        if j.id in false_ids:
            if start is not None:
                busy = min(finish, shift) - start
                out["served_false"] += 1
                out["inspection"] += busy
                out["unavailable"] += busy
                out["bottleneck_unavailable"] += busy if j.priority == 3 else 0.0
            continue
        if j.id not in fails:
            continue
        t_fail = fails[j.id]
        if start is not None and start < t_fail:  # repaired ahead of the failure
            out["prevented"] += 1
            unplanned, planned = 0.0, min(finish, shift) - start
        else:
            unplanned, planned = min(finish if finish is not None else shift, shift) - t_fail, 0.0
        out["planned_repair"] += planned
        out["unplanned"] += unplanned
        out["unavailable"] += unplanned + planned
        if j.priority == 3:
            out["bottleneck_unplanned"] += unplanned
            out["bottleneck_unavailable"] += unplanned + planned
    return out | {"failures": len(fails), "false_alarms": n_false}


def ci(base, other):
    """Paired bootstrap: mean saving (base - other) per shift and its 95% CI."""
    d = np.array(base) - np.array(other)
    rng = np.random.default_rng(0)
    boots = [rng.choice(d, len(d)).mean() for _ in range(5000)]
    return round(float(d.mean()), 1), [
        round(float(np.percentile(boots, 2.5)), 1),
        round(float(np.percentile(boots, 97.5)), 1),
    ]


def main(argv=None):
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=OUT, help="output path prefix (.log and .json are added)")
    ap.add_argument("--quick", action="store_true", help="4 shifts and three scenarios (smoke test)")
    ap.add_argument("--shifts", type=int, help="paired shifts (seeds) per scenario (default 40; 4 with --quick)")
    ap.add_argument("--engineers", type=int, default=E)
    ap.add_argument("--jobs", type=int, default=J)
    ap.add_argument("--workers", type=int, default=8, help="worker processes")
    args = ap.parse_args(argv)
    OUT = args.out
    seeds = range(args.shifts or (4 if args.quick else 40))
    e, j = args.engineers, args.jobs
    scenarios = [s for s in SCENARIOS if s[0] in QUICK] if args.quick else SCENARIOS

    def mean(rows, key):
        return round(float(np.mean([x[key] for x in rows])), 1)

    results = {}
    with _pool(args.workers) as ex:
        for name, recall, precision, lead in scenarios:
            r = results[name] = list(ex.map(run, [(s, recall, precision, lead, e, j) for s in seeds]))
            log(
                f"{name:15s} unplanned {mean(r, 'unplanned'):7.1f}  unavailable {mean(r, 'unavailable'):7.1f}  "
                f"(planned repair {mean(r, 'planned_repair'):6.1f}, inspections {mean(r, 'inspection'):5.1f})  "
                f"prevented {sum(x['prevented'] for x in r)}/{sum(x['failures'] for x in r)}"
            )
    base = results["reactive"]
    report = []
    for name, recall, precision, lead in scenarios:
        r = results[name]
        row = {
            "scenario": name,
            "recall": recall,
            "precision": precision,
            "lead_min": lead,
            "unplanned_downtime_min": mean(r, "unplanned"),
            "planned_repair_min": mean(r, "planned_repair"),
            "inspection_min": mean(r, "inspection"),
            "tool_unavailable_min": mean(r, "unavailable"),
            "bottleneck_unplanned_downtime_min": mean(r, "bottleneck_unplanned"),
            "bottleneck_tool_unavailable_min": mean(r, "bottleneck_unavailable"),
            "prevented_pct": round(100 * sum(x["prevented"] for x in r) / sum(x["failures"] for x in r), 1),
            "false_alarms_per_shift": mean(r, "false_alarms"),
            "false_alarms_served_per_shift": mean(r, "served_false"),
            "false_alarm_engineer_min": mean(r, "inspection"),
        }
        for key, label in (
            ("unplanned", "unplanned_saved"),
            ("unavailable", "availability_gain"),
            ("bottleneck_unplanned", "bottleneck_unplanned_saved"),
            ("bottleneck_unavailable", "bottleneck_availability_gain"),
        ):
            row[f"{label}_min"], row[f"{label}_ci95"] = ci([x[key] for x in base], [x[key] for x in r])
        report.append(row)
        log(
            f"  {name:15s} unplanned saved {row['unplanned_saved_min']} {row['unplanned_saved_ci95']}, "
            f"net availability gain {row['availability_gain_min']} {row['availability_gain_ci95']}, "
            f"bottleneck {row['bottleneck_availability_gain_min']} {row['bottleneck_availability_gain_ci95']}"
        )
    with open(OUT + ".json", "w") as f:
        json.dump(
            {
                "shifts": len(seeds),
                "algorithm": ALGO,
                "size": f"{e}x{j} normal",
                "quick": args.quick,
                "scenarios": report,
            },
            f,
            indent=1,
        )
    return report


if __name__ == "__main__":
    main()
