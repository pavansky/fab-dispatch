"""20,000 engineers: what planning every area of a company and a live event actually cost.

    python -m scripts.scale_study out/company                # writes .log and .json
    python -m scripts.scale_study out/smoke --areas 4 --events 10 --sizes 100x300

Measures (1) every area of a 20,000-engineer company planned in parallel, each a fresh
``allocate`` of its own shift (independent problems, not a re-plan of one), with how many
areas hit the solver's safety cap and what that cap cost against an uncapped solve of the
same areas; (2) live tool-down re-plan latency through the real live-dispatch code, with
events spread over the whole shift and the number of open jobs at each; (3) single
undecomposed large problems, with each solver's iterations and whether it hit the cap.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

OUT = ""


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def solve_area(args):
    seed, time_limit_s = args
    from app.engine import allocate
    from app.generator import generate
    from app.models import Weights

    sc = generate(seed, 30, 100, "normal")
    t = time.perf_counter()
    r = allocate(sc, Weights(), "pyvrp", time_limit_s=time_limit_s)
    return {
        "seed": seed,
        "seconds": time.perf_counter() - t,
        "coverage_pct": r.metrics["coverage_pct"],
        "objective": r.metrics["objective"],
        "iterations": r.solver.get("iterations"),
        "hit_time_cap": bool(r.solver.get("hit_time_cap")),
        "downs": sum(1 for j in sc.jobs if j.kind == "down"),
    }


def big(args):
    e, j, algo = args
    from app.engine import allocate
    from app.generator import generate
    from app.models import Weights

    sc = generate(1, e, j, "normal")
    t = time.perf_counter()
    r = allocate(sc, Weights(), algo)
    return {
        "size": f"{e}x{j}",
        "algorithm": algo,
        "seconds": time.perf_counter() - t,
        "objective": r.metrics["objective"],
        "coverage_pct": r.metrics["coverage_pct"],
        "iterations": r.solver.get("iterations"),
        "hit_time_cap": bool(r.solver.get("hit_time_cap")),
        "warm_start_s": r.solver.get("warm_start_s"),
        "search_s": r.solver.get("search_s"),
    }


def save(report: dict) -> None:
    """Written after every section, so a run killed in a later one keeps the earlier results."""
    with open(OUT + ".json", "w") as f:
        json.dump(report, f, indent=1)


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--areas", type=int, default=222, help="areas of 30 x 100 (222 = 6,660 engineers on shift)")
    ap.add_argument("--events", type=int, default=50, help="live tool-downs spread over the shift")
    ap.add_argument("--sizes", default="100x300,150x500,300x1000", help="undecomposed sizes, ExJ comma-separated")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    OUT = args.out
    from app.config import get_settings

    cap = get_settings().solver_time_limit_s
    workers = args.workers
    report = {
        "platform": f"{platform.processor() or platform.machine()}, {os.cpu_count()} CPUs, {platform.system()}",
        "solver_time_limit_s": cap,
    }
    log(f"platform: {report['platform']}; solver safety cap {cap} s")

    # 1. whole company: areas of 30 x 100 (20,000 engineers / 3 shifts / 30 per area = 222),
    #    each a fresh plan of its own shift.
    areas = args.areas
    log(
        f"company plan: {areas} areas x (30 engineers, 100 jobs) = {areas * 30:,} engineers on shift, {workers} workers"
    )
    t = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(solve_area, [(s, None) for s in range(areas)]))
    wall = time.perf_counter() - t
    capped = [r for r in res if r["hit_time_cap"]]
    secs = sorted(r["seconds"] for r in res)
    report["company"] = {
        "areas": areas,
        "engineers_on_shift": areas * 30,
        "jobs": areas * 100,
        "workers": workers,
        "wall_s": wall,
        "cpu_s": sum(secs),
        "per_area_p50_s": statistics.median(secs),
        "per_area_p95_s": secs[min(len(secs) - 1, int(0.95 * areas))],
        "coverage_mean_pct": statistics.fmean(r["coverage_pct"] for r in res),
        "iterations_mean": statistics.fmean(r["iterations"] for r in res),
        "areas_hit_time_cap": len(capped),
        "downs_total": sum(r["downs"] for r in res),
    }
    c = report["company"]
    log(
        f"company plan: wall {wall:.1f}s on {workers} workers, {c['cpu_s']:.0f} CPU-s total, per area p50 "
        f"{c['per_area_p50_s']:.2f}s p95 {c['per_area_p95_s']:.2f}s, {c['iterations_mean']:.0f} PyVRP iterations on "
        f"average, {len(capped)}/{areas} areas hit the {cap} s cap"
    )
    if capped:
        # The same areas again with no cap: what the cap cost in plan quality and time.
        with ProcessPoolExecutor(workers) as ex:
            free = list(ex.map(solve_area, [(r["seed"], 3600.0) for r in capped]))
        worse = [
            100 * (a["objective"] - b["objective"]) / abs(b["objective"]) for a, b in zip(capped, free, strict=True)
        ]
        report["company"]["capped_vs_uncapped"] = {
            "areas": len(capped),
            "capped_cost_mean": statistics.fmean(r["objective"] for r in capped),
            "uncapped_cost_mean": statistics.fmean(r["objective"] for r in free),
            "capped_cost_above_uncapped_pct_mean": statistics.fmean(worse),
            "capped_cost_above_uncapped_pct_max": max(worse),
            "uncapped_seconds_p50": statistics.median(r["seconds"] for r in free),
            "uncapped_iterations_mean": statistics.fmean(r["iterations"] for r in free),
        }
        u = report["company"]["capped_vs_uncapped"]
        log(
            f"capped areas re-solved without the cap: {u['uncapped_iterations_mean']:.0f} iterations in "
            f"{u['uncapped_seconds_p50']:.2f}s p50; capped plans cost {u['capped_cost_above_uncapped_pct_mean']:.2f}% more "
            f"on average (max {u['capped_cost_above_uncapped_pct_max']:.2f}%)"
        )
    # Tool-down rate implied by the generated shifts, not assumed: downs per shift across the
    # company, over the shift length.
    from app.fabs import get_profile

    shift_s = get_profile("fab1-300mm-logic").shift.length_min * 60
    report["company"]["downs_per_second"] = c["downs_total"] / shift_s
    log(
        f"generated shifts hold {c['downs_total']:,} tool-downs across {areas} areas: "
        f"{c['downs_per_second']:.3f} tool-downs per second over a {shift_s // 60}-minute shift"
    )

    save(report)

    # 2. live events: tool-downs reported into one live 30 x 100 shift through the real live
    #    code, spread over the whole shift so the open-job count varies as it would in practice.
    from app import live
    from app.generator import generate
    from app.models import Job, Weights

    sc = generate(7, 30, 100, "normal")
    state, _ = live.start(sc, Weights(), "alns")
    shift_len = state.shift_length
    events = []
    for i in range(args.events):
        clock = shift_len * (i + 0.5) / args.events
        live.advance(state, clock - state.clock)
        base = sc.jobs[i % len(sc.jobs)]
        job = Job(id=f"EV{i}", x=base.x, y=base.y, skill=base.skill, priority=3, earliest=0, latest=90, duration=45)
        before = live.progress(state)
        t = time.perf_counter()
        live.report_job(state, job, "load-test")
        events.append(
            {
                "clock": round(state.clock, 1),
                "open_jobs_before": before["planned"] + before["in_progress"] + before["unassigned"],
                "known_jobs_before": before["known"],
                "seconds": time.perf_counter() - t,
                "hit_time_cap": bool(state.plan.solver.get("hit_time_cap")),
                "iterations": state.plan.solver.get("iterations"),
            }
        )
    lat = sorted(e["seconds"] for e in events)
    n = len(lat)
    report["live_events"] = {
        "events": n,
        "p50_s": statistics.median(lat),
        "p95_s": lat[min(n - 1, int(0.95 * n))],
        "max_s": lat[-1],
        "open_jobs_min": min(e["open_jobs_before"] for e in events),
        "open_jobs_max": max(e["open_jobs_before"] for e in events),
        "events_hit_time_cap": sum(e["hit_time_cap"] for e in events),
        "per_event": events,
    }
    le = report["live_events"]
    log(
        f"live events: {n} tool-downs re-planned at clocks {events[0]['clock']:.0f}..{events[-1]['clock']:.0f} of "
        f"{shift_len}, open jobs {le['open_jobs_min']}..{le['open_jobs_max']}, p50 {le['p50_s'] * 1000:.0f} ms, "
        f"p95 {le['p95_s'] * 1000:.0f} ms, max {le['max_s'] * 1000:.0f} ms, {le['events_hit_time_cap']}/{n} hit the live cap"
    )
    log(
        f"one core serves about {1 / le['p50_s']:.1f} re-plans per second at the median; the generated company "
        f"rate above is {c['downs_per_second']:.3f} tool-downs per second"
    )

    save(report)

    # 3. no decomposition: single large problems (300 x 1000 needs several GB for PyVRP's matrices)
    report["single_large"] = []
    for size in args.sizes.split(","):
        e, j = (int(x) for x in size.split("x"))
        for algo in ("regret", "alns", "pyvrp"):
            r = big((e, j, algo))
            report["single_large"].append(r)
            save(report)
            log(
                f"single {e}x{j} {algo}: {r['seconds']:.1f}s, cost {r['objective']:.0f}, coverage {r['coverage_pct']:.1f}%, "
                f"iterations {r['iterations']}, hit cap {r['hit_time_cap']}, warm start {r['warm_start_s']}s, "
                f"search {r['search_s']}s"
            )
    save(report)
    log("done")


if __name__ == "__main__":
    sys.exit(main())
