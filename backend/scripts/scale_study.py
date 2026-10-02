"""20,000 engineers: what a whole-company re-plan and a live event actually cost.

    python -m scripts.scale_study out/company   # writes .log and .json

Measures (1) all areas of a 20,000-engineer company re-planned in parallel, (2) live tool-down
re-plan latency through the real live-dispatch code, (3) single undecomposed large problems.
"""

import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

OUT = sys.argv[1]


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def solve_area(seed):
    from app.engine import allocate
    from app.generator import generate
    from app.models import Weights

    sc = generate(seed, 30, 100, "normal")
    t = time.perf_counter()
    r = allocate(sc, Weights(), "pyvrp")
    return time.perf_counter() - t, r.metrics["coverage_pct"]


def big(args):
    e, j, algo = args
    from app.engine import allocate
    from app.generator import generate
    from app.models import Weights

    sc = generate(1, e, j, "normal")
    t = time.perf_counter()
    r = allocate(sc, Weights(), algo)
    return e, j, algo, time.perf_counter() - t, r.metrics["objective"], r.metrics["coverage_pct"]


if __name__ == "__main__":
    workers = max(1, (os.cpu_count() or 4) - 2)
    report = {}
    # 1. whole company: 222 areas of 30 x 100 (20,000 engineers / 3 shifts / 30 per area)
    areas = 222
    log(
        f"company re-plan: {areas} areas x (30 engineers, 100 jobs) = {areas * 30:,} engineers on shift, {workers} workers"
    )
    t = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(solve_area, range(areas)))
    wall = time.perf_counter() - t
    cpu = sum(r[0] for r in res)
    report["company"] = {
        "areas": areas,
        "engineers_on_shift": areas * 30,
        "jobs": areas * 100,
        "workers": workers,
        "wall_s": wall,
        "cpu_s": cpu,
        "per_area_p50_s": statistics.median(r[0] for r in res),
        "per_area_p95_s": sorted(r[0] for r in res)[int(0.95 * areas)],
        "coverage_mean_pct": statistics.fmean(r[1] for r in res),
    }
    log(
        f"company re-plan: wall {wall:.1f}s on {workers} workers, {cpu:.0f} CPU-s total, per area p50 {report['company']['per_area_p50_s']:.2f}s p95 {report['company']['per_area_p95_s']:.2f}s"
    )

    # 2. live events: 50 tool-downs into one live 30 x 100 shift, through the real live code
    from app import live
    from app.generator import generate
    from app.models import Job, Weights

    sc = generate(7, 30, 100, "normal")
    state, _ = live.start(sc, Weights(), "alns")
    lat = []
    for i in range(50):
        live.advance(state, 5)
        base = sc.jobs[i % len(sc.jobs)]
        job = Job(id=f"EV{i}", x=base.x, y=base.y, skill=base.skill, priority=3, earliest=0, latest=90, duration=45)
        t = time.perf_counter()
        live.report_job(state, job, "load-test")
        lat.append(time.perf_counter() - t)
    lat.sort()
    report["live_events"] = {"events": 50, "p50_s": lat[25], "p95_s": lat[47], "max_s": lat[-1]}
    log(
        f"live events: 50 tool-downs re-planned, p50 {lat[25] * 1000:.0f} ms, p95 {lat[47] * 1000:.0f} ms, max {lat[-1] * 1000:.0f} ms"
    )

    # 3. no decomposition: single large problems
    sizes = [(100, 300), (150, 500), (300, 1000)]
    report["single_large"] = []
    for e, j in sizes:
        for algo in ("regret", "alns", "pyvrp"):
            e_, j_, a, s, obj, cov = big((e, j, algo))
            report["single_large"].append(
                {"size": f"{e}x{j}", "algorithm": a, "seconds": s, "objective": obj, "coverage_pct": cov}
            )
            log(f"single {e}x{j} {a}: {s:.1f}s, cost {obj:.0f}, coverage {cov:.1f}%")
    with open(OUT + ".json", "w") as f:
        json.dump(report, f, indent=1)
    log("done")
