"""Does planning on failure predictions beat reacting to breakdowns? A mock predictive-maintenance feed.

    python -m scripts.predictive_study out/predictive   # writes .log and .json

Every tool-down in a generated shift is a failure at a known minute. Reactive dispatch (today)
learns of it when it happens. A predictor flags a share of failures (recall) some minutes ahead
(lead time); a flagged failure enters the live plan as a job at prediction time, so an engineer can
repair it before the tool goes down. Predictors also raise false alarms (precision): each one costs
a 45-minute inspection that finds nothing.

The shift is replayed through the real live-dispatch code (app/live.py: re-plan at every event,
started work frozen). Measured per shift: unplanned downtime (minutes a tool is down before its
repair finishes; an unrepaired failure counts until shift end), split out for bottleneck tools.
A failure repaired before it happens has no unplanned downtime. Shifts are paired across
scenarios (same seed), with a bootstrap 95% CI on the saving.
"""

import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

OUT = sys.argv[1] if len(sys.argv) > 1 else "out/predictive"
SEEDS = range(40)
ALGO = "regret"  # live re-plans run at every event; regret-2 keeps 40 shifts x 9 scenarios in minutes
INSPECTION_MIN = 45

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


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def run(args):
    seed, recall, precision, lead = args
    from app import live
    from app.generator import generate
    from app.models import Weights

    sc = generate(seed, 14, 45, "normal")
    rng = random.Random(1000 + seed)  # the same failures are flagged across lead/precision sweeps
    fails = {j.id: j.earliest for j in sc.jobs if j.kind == "down"}
    jobs, flagged = [], 0
    for j in sc.jobs:
        if j.kind == "down" and rng.random() < recall:
            flagged += 1
            jobs.append(j.model_copy(update={"earliest": max(0, j.earliest - lead)}))
        else:
            jobs.append(j)
    n_false = round(flagged * (1 - precision) / precision) if flagged else 0
    downs = [j for j in sc.jobs if j.kind == "down"]
    for i in range(n_false):
        src = rng.choice(downs)
        t = rng.randint(0, 400)
        jobs.append(
            src.model_copy(
                update={"id": f"F{i:03d}", "earliest": t, "latest": t + 120, "duration": INSPECTION_MIN, "priority": 2}
            )
        )
    sc = sc.model_copy(update={"jobs": jobs})

    state, _ = live.start(sc, Weights(), ALGO)
    live.advance(state, state.shift_length)
    end = {s.job_id: (s.start, s.end) for r in state.plan.routes for s in r.stops}
    shift = state.shift_length
    total = bottleneck = 0.0
    prevented = 0
    for j in sc.jobs:
        if j.id not in fails:
            continue
        t_fail = fails[j.id]
        start, finish = end.get(j.id, (None, None))
        if start is not None and start < t_fail:
            prevented += 1
            down = 0.0
        else:
            down = (finish if finish is not None else shift) - t_fail
        total += down
        bottleneck += down if j.priority == 3 else 0.0
    return {
        "downtime": total,
        "bottleneck": bottleneck,
        "prevented": prevented,
        "failures": len(fails),
        "false_alarms": n_false,
    }


def ci(base, other):
    d = np.array(base) - np.array(other)
    rng = np.random.default_rng(0)
    boots = [rng.choice(d, len(d)).mean() for _ in range(5000)]
    return round(float(d.mean()), 1), [
        round(float(np.percentile(boots, 2.5)), 1),
        round(float(np.percentile(boots, 97.5)), 1),
    ]


def main():
    results = {}
    with ProcessPoolExecutor() as ex:
        for name, recall, precision, lead in SCENARIOS:
            results[name] = list(ex.map(run, [(s, recall, precision, lead) for s in SEEDS]))
            r = results[name]
            log(
                f"{name:15s} downtime {np.mean([x['downtime'] for x in r]):7.1f}  "
                f"bottleneck {np.mean([x['bottleneck'] for x in r]):6.1f}  "
                f"prevented {sum(x['prevented'] for x in r)}/{sum(x['failures'] for x in r)}"
            )
    base = results["reactive"]
    report = []
    for name, recall, precision, lead in SCENARIOS:
        r = results[name]
        saved, saved_ci = ci([x["downtime"] for x in base], [x["downtime"] for x in r])
        bsaved, bsaved_ci = ci([x["bottleneck"] for x in base], [x["bottleneck"] for x in r])
        report.append(
            {
                "scenario": name,
                "recall": recall,
                "precision": precision,
                "lead_min": lead,
                "downtime_min": round(float(np.mean([x["downtime"] for x in r])), 1),
                "bottleneck_downtime_min": round(float(np.mean([x["bottleneck"] for x in r])), 1),
                "prevented_pct": round(100 * sum(x["prevented"] for x in r) / sum(x["failures"] for x in r), 1),
                "false_alarms_per_shift": round(float(np.mean([x["false_alarms"] for x in r])), 1),
                "saved_min": saved,
                "saved_ci95": saved_ci,
                "bottleneck_saved_min": bsaved,
                "bottleneck_saved_ci95": bsaved_ci,
            }
        )
        log(f"  {name:15s} saves {saved} min/shift {saved_ci}, bottleneck {bsaved} {bsaved_ci}")
    with open(OUT + ".json", "w") as f:
        json.dump({"shifts": len(SEEDS), "algorithm": ALGO, "size": "14x45 normal", "scenarios": report}, f, indent=1)


if __name__ == "__main__":
    main()
