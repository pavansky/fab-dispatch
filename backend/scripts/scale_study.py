"""20,000 engineers: what a whole-company re-plan and a live event actually cost.

    python -m scripts.scale_study out/company   # writes .log and .json

Measures (1) all areas of a 20,000-engineer company re-planned in parallel, (2) live tool-down
re-plan latency through the real live-dispatch code, (3) single undecomposed large problems.
The size flags exist for the smoke test (``tests/test_scripts.py``); the defaults are the study.
"""

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor

OUT = "out/company"


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


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def solve_area(args):
    seed, e, j = args
    from app.engine import allocate
    from app.generator import generate
    from app.models import Weights

    sc = generate(seed, e, j, "normal")
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


def _size(text: str) -> tuple[int, int]:
    e, j = text.lower().split("x")
    return int(e), int(j)


def main(argv: list[str] | None = None) -> dict:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=OUT, help="output path prefix (.log and .json are added)")
    # 222 areas of 30 x 100: 20,000 engineers / 3 shifts / 30 per area.
    ap.add_argument("--areas", type=int, default=222, help="areas re-planned in parallel")
    ap.add_argument("--area-size", type=_size, default=(30, 100), help="engineers x jobs per area")
    ap.add_argument("--events", type=int, default=50, help="tool-downs reported into one live shift")
    ap.add_argument("--sizes", default="100x300,150x500,300x1000", help="undecomposed problem sizes, comma-separated")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args(argv)
    OUT = args.out
    workers, areas = args.workers, args.areas
    ae, aj = args.area_size
    report = {}
    # 1. whole company, every area re-planned in parallel
    log(
        f"company re-plan: {areas} areas x ({ae} engineers, {aj} jobs) = {areas * ae:,} engineers on shift, {workers} workers"
    )
    t = time.perf_counter()
    with _pool(workers) as ex:
        res = list(ex.map(solve_area, [(seed, ae, aj) for seed in range(areas)]))
    wall = time.perf_counter() - t
    cpu = sum(r[0] for r in res)
    report["company"] = {
        "areas": areas,
        "engineers_on_shift": areas * ae,
        "jobs": areas * aj,
        "workers": workers,
        "wall_s": wall,
        "cpu_s": cpu,
        "per_area_p50_s": statistics.median(r[0] for r in res),
        "per_area_p95_s": sorted(r[0] for r in res)[min(areas - 1, int(0.95 * areas))],
        "coverage_mean_pct": statistics.fmean(r[1] for r in res),
    }
    log(
        f"company re-plan: wall {wall:.1f}s on {workers} workers, {cpu:.0f} CPU-s total, per area p50 {report['company']['per_area_p50_s']:.2f}s p95 {report['company']['per_area_p95_s']:.2f}s"
    )

    # 2. live events: tool-downs into one live area-sized shift, through the real live code
    from app import live
    from app.generator import generate
    from app.models import Job, Weights

    sc = generate(7, ae, aj, "normal")
    state, _ = live.start(sc, Weights(), "alns")
    lat = []
    n_events = args.events
    for i in range(n_events):
        live.advance(state, 5)
        base = sc.jobs[i % len(sc.jobs)]
        job = Job(id=f"EV{i}", x=base.x, y=base.y, skill=base.skill, priority=3, earliest=0, latest=90, duration=45)
        t = time.perf_counter()
        live.report_job(state, job, "load-test")
        lat.append(time.perf_counter() - t)
    lat.sort()
    p50, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    report["live_events"] = {"events": n_events, "p50_s": p50, "p95_s": p95, "max_s": lat[-1]}
    log(
        f"live events: {n_events} tool-downs re-planned, p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms, max {lat[-1] * 1000:.0f} ms"
    )

    # 3. no decomposition: single large problems
    report["single_large"] = []
    for e, j in (_size(s) for s in args.sizes.split(",") if s):
        for algo in ("regret", "alns", "pyvrp"):
            _, _, a, s, obj, cov = big((e, j, algo))
            report["single_large"].append(
                {"size": f"{e}x{j}", "algorithm": a, "seconds": s, "objective": obj, "coverage_pct": cov}
            )
            log(f"single {e}x{j} {a}: {s:.1f}s, cost {obj:.0f}, coverage {cov:.1f}%")
    with open(OUT + ".json", "w") as f:
        json.dump(report, f, indent=1)
    log("done")
    return report


if __name__ == "__main__":
    main()
