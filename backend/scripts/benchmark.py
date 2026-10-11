"""Benchmark every strategy; prints Markdown for docs/ANALYSIS.md.

    python -m scripts.benchmark --seeds 20                  # static: every job known at t=0
    python -m scripts.benchmark --seeds 20 --mode revealed  # jobs become known at reported_at
    python -m scripts.benchmark --only gaps-full            # the proven-optimum study (slow)

Studies:
1. quality across the four scenario presets (mean over seeded shifts, lowest-cost wins, and a
   paired bootstrap 95% CI of each strategy's cost difference to PyVRP)
2. optimality gap against the proven optimum (exact MILP), at full shift size, per preset
3. runtime scaling with problem size (median of several runs, platform printed)
4. the iteration budget curve, including ALNS at PyVRP's wall time

``--mode static`` (default) hands every strategy the whole shift at t=0: it assumes full
foresight of tool-downs that are in fact reported later. ``--mode revealed`` replays each shift
through the live-dispatch code (app/live.py): jobs become known at ``reported_at``, the shift is
re-planned at every reveal with started work frozen, and the realised plan is scored.
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import statistics
import time
from collections import defaultdict
from collections.abc import Callable

from app import live
from app.algorithms import ALGORITHMS
from app.algorithms.exact import run_exact
from app.engine import allocate
from app.fabs import get_profile
from app.generator import generate
from app.models import Scenario, Weights
from app.planner import Planner

PRESETS = get_profile("fab1-300mm-logic").presets
REFERENCE = "pyvrp"  # the strategy every cost difference is measured against
BOOTSTRAP_RESAMPLES = 5000
TIMING_RUNS = 5

COLUMNS = [
    ("coverage_pct", "Coverage %"),
    ("critical_coverage_pct", "Bottleneck %"),
    ("mean_response_min", "Response min"),
    ("walk_m_per_job", "Walk m/job"),
    ("wait_min_total", "Idle wait min"),
    ("workload_std", "Load std"),
    ("objective", "Cost ↓"),
    ("runtime_ms", "ms"),
]


def paired_bootstrap_ci(diffs: list[float], seed: int = 0) -> tuple[float, float]:
    """Percentile 95% CI of the mean of paired differences (seeded, 5000 resamples)."""
    rng = random.Random(seed)
    k = len(diffs)
    means = sorted(statistics.fmean(rng.choices(diffs, k=k)) for _ in range(BOOTSTRAP_RESAMPLES))
    return means[int(0.025 * BOOTSTRAP_RESAMPLES)], means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]


def run_static(sc: Scenario, algorithm: str) -> dict[str, float]:
    return allocate(sc, Weights(), algorithm).metrics


def run_revealed(sc: Scenario, algorithm: str) -> dict[str, float]:
    """Replay the shift through app.live: start with the jobs known at t=0, then advance to
    each reveal time, re-planning there with started work frozen. Returns the realised plan's
    metrics. ``objective`` is its operating + workload cost (what the shift cost in walking,
    waiting, over-qualification, unserved penalty and balance); the stability charge of the
    final re-plan is reported separately as ``reassignment_cost``. ``runtime_ms`` is the sum
    over every re-plan, and ``capped_replans`` counts re-plans that hit the live time cap."""
    state, _ = live.start(sc, Weights(), algorithm)
    runtime = state.plan.metrics["runtime_ms"]
    capped = int(bool(state.plan.solver.get("hit_time_cap")))
    for when in sorted({j.reported_at for j in sc.jobs if j.reported_at > 0}):
        live.advance(state, when - state.clock)
        runtime += state.plan.metrics["runtime_ms"]
        capped += int(bool(state.plan.solver.get("hit_time_cap")))
    live.advance(state, state.shift_length - state.clock)
    m = dict(state.plan.metrics)
    m["objective"] = round(m["operating_cost"] + m["workload_cost"], 1)
    m["runtime_ms"] = round(runtime, 2)
    m["replans"] = state.replans
    m["capped_replans"] = capped
    return m


def quality(seeds: int, engineers: int, jobs: int, mode: str) -> None:
    run: Callable[[Scenario, str], dict[str, float]] = run_static if mode == "static" else run_revealed
    for preset in PRESETS:
        rows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        wins: dict[str, int] = defaultdict(int)
        for seed in range(seeds):
            sc = generate(seed, engineers, jobs, preset)
            res = {a: run(sc, a) for a in ALGORITHMS}
            best = min(m["objective"] for m in res.values())
            for a, m in res.items():
                wins[a] += m["objective"] <= best + 1e-6
                for k in [*(k for k, _ in COLUMNS), "replans", "capped_replans"]:
                    if k in m:
                        rows[a][k].append(m[k])
        print(f"\n#### {PRESETS[preset].label}" + (" (revealed)" if mode == "revealed" else "") + "\n")
        print("| Strategy | " + " | ".join(t for _, t in COLUMNS) + f" | Lowest cost | Cost vs {REFERENCE} [95% CI] |")
        print("|---" * (len(COLUMNS) + 3) + "|")
        for a in ALGORITHMS:
            cells = [f"{statistics.fmean(rows[a][k]):.1f}" for k, _ in COLUMNS]
            if a == REFERENCE:
                ci = "reference"
            else:
                diffs = [x - y for x, y in zip(rows[a]["objective"], rows[REFERENCE]["objective"], strict=True)]
                lo, hi = paired_bootstrap_ci(diffs)
                ci = f"{statistics.fmean(diffs):+.1f} [{lo:+.1f}, {hi:+.1f}]"
            print(f"| {a} | " + " | ".join(cells) + f" | {wins[a]}/{seeds} | {ci} |")
        if mode == "revealed":
            replans = statistics.fmean(rows[REFERENCE]["replans"])
            capped = {a: sum(rows[a]["capped_replans"]) for a in ALGORITHMS}
            total = {a: sum(rows[a]["replans"]) for a in ALGORITHMS}
            print(
                f"\n{replans:.0f} re-plans per shift (one per reveal time); ms is the sum over them. "
                "Re-plans that hit the live time cap: "
                + ", ".join(f"{a} {capped[a]}/{total[a]}" for a in ALGORITHMS)
                + "."
            )


def uncoverable_penalty(p: Planner) -> float:
    """Reward forgone on jobs that no engineer in the instance is certified for: every plan,
    the optimum included, pays it, so it can't be changed by any strategy."""
    return sum(
        p.w.priority_reward * j.priority
        for jid, j in p.open_jobs.items()
        if all(p.tech_can_do(t, jid) is not None for t in p.techs)
    )


def gaps_full(seeds: int, engineers: int, jobs: int) -> None:
    """Gap to the proven optimum on full-size shifts, per preset. Any negative gap would mean
    the "optimum" isn't one, so it fails loudly instead of printing a flattering table.

    Two gaps are printed: on the whole cost, and on the *changeable* cost, (strategy - optimum)
    / (optimum - penalty of jobs no engineer on shift can serve). In the litho crunch most of
    the cost is that fixed penalty, which deflates the whole-cost gap."""
    print(
        "\n| Preset | Strategy | Mean gap % | Worst gap % | Mean gap % on changeable cost | Optimal in |"
        "\n|---|---|---|---|---|---|"
    )
    overall: dict[str, list[float]] = defaultdict(list)
    overall_ch: dict[str, list[float]] = defaultdict(list)
    exact_s, columns, fixed_share = [], [], []
    for preset in PRESETS:
        per: dict[str, list[float]] = defaultdict(list)
        per_ch: dict[str, list[float]] = defaultdict(list)
        for seed in range(seeds):
            sc = generate(seed, engineers, jobs, preset)
            p = Planner(sc, Weights())
            fixed = uncoverable_penalty(p)
            t0 = time.perf_counter()
            run_exact(p)
            exact_s.append(time.perf_counter() - t0)
            columns.append(p.meta["solver"]["columns"])
            opt = p.total_cost()
            fixed_share.append(fixed / opt if opt else 0.0)
            for a, (_, fn) in ALGORITHMS.items():
                q = Planner(sc, Weights())
                fn(q)
                g = 100 * (q.total_cost() - opt) / abs(opt)
                assert g > -1e-6, f"{a} beat the 'optimum' on {preset} seed {seed}: {g:.4f}%"
                per[a].append(g)
                overall[a].append(g)
                g_ch = 100 * (q.total_cost() - opt) / abs(opt - fixed)
                per_ch[a].append(g_ch)
                overall_ch[a].append(g_ch)
        for a in ALGORITHMS:
            hits = sum(g < 0.01 for g in per[a])
            print(
                f"| {PRESETS[preset].label} | {a} | {statistics.fmean(per[a]):.2f} | {max(per[a]):.2f} | "
                f"{statistics.fmean(per_ch[a]):.2f} | {hits}/{seeds} |"
            )
    print(
        "\n| Strategy | Mean gap % (all presets) | Worst gap % | Mean gap % on changeable cost | Optimal in |"
        "\n|---|---|---|---|---|"
    )
    for a in ALGORITHMS:
        g = overall[a]
        print(
            f"| {a} | {statistics.fmean(g):.2f} | {max(g):.2f} | {statistics.fmean(overall_ch[a]):.2f} | "
            f"{sum(x < 0.01 for x in g)}/{len(g)} |"
        )
    print(
        f"\nExact solve (enumerate + MILP): mean {statistics.fmean(exact_s):.1f} s, max {max(exact_s):.1f} s; "
        f"{statistics.fmean(columns):,.0f} routes per shift on average. Uncoverable penalty is "
        f"{100 * statistics.fmean(fixed_share):.0f}% of the optimum on average (max {100 * max(fixed_share):.0f}%)."
    )


def gaps(seeds: int) -> None:
    per: dict[str, list[float]] = defaultdict(list)
    worst: dict[str, float] = defaultdict(float)
    optimal_hits: dict[str, int] = defaultdict(int)
    for seed in range(seeds):
        sc = generate(seed, 4, 12, "normal")
        p = Planner(sc, Weights())
        run_exact(p)
        opt = p.total_cost()
        for a, (_, fn) in ALGORITHMS.items():
            q = Planner(sc, Weights())
            fn(q)
            g = 100 * (q.total_cost() - opt) / abs(opt)
            per[a].append(g)
            worst[a] = max(worst[a], g)
            optimal_hits[a] += g < 0.01
    print("\n| Strategy | Mean gap % | Worst gap % | Optimal in |\n|---|---|---|---|")
    for a in ALGORITHMS:
        print(f"| {a} | {statistics.fmean(per[a]):.2f} | {worst[a]:.2f} | {optimal_hits[a]}/{seeds} |")


def platform_line() -> str:
    return (
        f"{platform.processor() or platform.machine()}, {os.cpu_count()} CPUs, "
        f"{platform.system()} {platform.machine()}, Python {platform.python_version()}"
    )


def scaling(runs: int = TIMING_RUNS) -> None:
    print(f"\nMedian of {runs} runs per cell on: {platform_line()}. * = hit the time cap in at least one run.")
    print("\n| Size | " + " | ".join(ALGORITHMS) + " |\n|---" * 1 + "|---" * len(ALGORITHMS) + "|")
    for e, j in [(14, 45), (30, 100), (60, 200)]:
        sc = generate(1, e, j, "normal")
        cells = []
        for a in ALGORITHMS:
            ms, capped = [], False
            for _ in range(runs):
                t0 = time.perf_counter()
                res = allocate(sc, Weights(), a)
                ms.append((time.perf_counter() - t0) * 1000)
                capped |= bool(res.solver.get("hit_time_cap"))
            cells.append(f"{statistics.median(ms):.0f}" + ("*" if capped else ""))
        print(f"| {e} engineers, {j} jobs | " + " | ".join(cells) + " |")


def budgets() -> None:
    """Cost of each extra iteration: where the quality curve flattens is the budget to ship.
    The last ALNS row gives it the iterations that match PyVRP's shipped wall time."""
    from app.algorithms.alns import run_alns
    from app.algorithms.pyvrp_ils import run_pyvrp
    from app.algorithms.regret import run_regret
    from app.config import get_settings

    scs = [generate(s, 14, 45, p) for s in range(6) for p in ("normal", "excursion")]

    def run(fn):
        costs, ts = [], []
        for sc in scs:
            p = Planner(sc, Weights())
            t0 = time.perf_counter()
            fn(p)
            ts.append((time.perf_counter() - t0) * 1000)
            costs.append(p.total_cost())
        return statistics.fmean(costs), statistics.fmean(ts)

    base, _ = run(run_regret)
    shipped = {"ALNS": get_settings().alns_iterations, "PyVRP": get_settings().pyvrp_iterations}
    print(f"\nOn: {platform_line()}")
    print("\n| Solver | Iterations | Cost below regret-2 | Mean solve ms |\n|---|---|---|---|")
    measured = {}
    for name, fn, its in (("ALNS", run_alns, (100, 300, 600)), ("PyVRP", run_pyvrp, (250, 1000, 3000))):
        for it in its:
            c, t = run(lambda p, fn=fn, it=it: fn(p, max_iterations=it, runtime_s=60))
            measured[(name, it)] = (c, t)
            mark = " (shipped)" if it == shipped[name] else ""
            print(f"| {name} | {it}{mark} | {100 * (base - c) / base:.1f}% | {t:.0f} |")
    # Equal wall time: ALNS with as many iterations as fit in PyVRP's shipped solve time.
    _, t_py = measured[("PyVRP", shipped["PyVRP"])]
    _, t_alns = measured[("ALNS", shipped["ALNS"])]
    matched = max(1, round(shipped["ALNS"] * t_py / t_alns))
    c, t = run(lambda p: run_alns(p, max_iterations=matched, runtime_s=60))
    print(f"| ALNS | {matched} (PyVRP {shipped['PyVRP']}'s wall time) | {100 * (base - c) / base:.1f}% | {t:.0f} |")


def set_alns_iterations(n: int) -> None:
    """Run every ALNS plan in this process with an ``n``-iteration budget and no time cap,
    so the gap at a larger budget (ANALYSIS "Distance from the proven optimum at full size")
    is reproducible: ``--alns-iterations 20000``."""
    from app.algorithms.alns import run_alns

    def run(p: Planner, *args, **kwargs):
        kwargs.setdefault("max_iterations", n)
        kwargs.setdefault("runtime_s", 3600)
        return run_alns(p, *args, **kwargs)

    ALGORITHMS["alns"] = (f"ALNS ({n} iterations)", run)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--engineers", type=int, default=14)
    ap.add_argument("--jobs", type=int, default=45)
    ap.add_argument("--gap-seeds", type=int, default=20)
    ap.add_argument("--mode", choices=["static", "revealed"], default="static", help="see the module docstring")
    ap.add_argument("--only", choices=["quality", "gaps", "gaps-full", "scaling", "budgets"], help="run one study")
    ap.add_argument("--alns-iterations", type=int, help="ALNS budget for every study (default: the shipped 300)")
    args = ap.parse_args()
    if args.alns_iterations:
        set_alns_iterations(args.alns_iterations)
    studies = {
        "quality": lambda: (
            print(
                f"### Quality ({args.seeds} seeds per preset, {args.engineers} engineers, {args.jobs} jobs, {args.mode})"
            ),
            quality(args.seeds, args.engineers, args.jobs, args.mode),
        ),
        "gaps": lambda: (
            print(f"\n### Optimality gap ({args.gap_seeds} shifts of 4 engineers x 12 jobs, exact MILP optimum)"),
            gaps(args.gap_seeds),
        ),
        "gaps-full": lambda: (
            print(
                f"### Optimality gap at full size ({args.gap_seeds} shifts per preset, {args.engineers} x {args.jobs})"
            ),
            gaps_full(args.gap_seeds, args.engineers, args.jobs),
        ),
        "scaling": lambda: (print("\n### Solve time (ms, one shift)"), scaling()),
        "budgets": lambda: (print("\n### Iteration budget (12 shifts)"), budgets()),
    }
    if args.only:
        studies[args.only]()
        return
    for name in ("quality", "gaps", "scaling", "budgets"):
        studies[name]()


if __name__ == "__main__":
    main()
