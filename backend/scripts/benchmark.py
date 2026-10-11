"""Benchmark every strategy; prints Markdown for docs/ANALYSIS.md.

    python -m scripts.benchmark --seeds 20
    python -m scripts.benchmark --only gaps-full --gap-seeds 20

Four studies, each printed as a Markdown table (and returned as rows, for the smoke tests):
1. quality across the four scenario presets (mean over seeded shifts, lowest-cost wins)
2. optimality gap against the proven optimum (exact MILP): small shifts by default, or at full
   shift size per preset with ``--only gaps-full``
3. runtime scaling with problem size
4. the iteration budget: what each extra ALNS / PyVRP iteration buys
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import defaultdict

from app.algorithms import ALGORITHMS
from app.algorithms.exact import run_exact
from app.engine import allocate
from app.fabs import get_profile
from app.generator import generate
from app.models import Weights
from app.planner import Planner

PRESETS = get_profile("fab1-300mm-logic").presets

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


def quality(seeds: int, engineers: int, jobs: int) -> dict[str, dict[str, dict[str, float]]]:
    """Mean of every metric per preset and strategy: {preset: {strategy: {metric: mean, "wins": n}}}."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for preset in PRESETS:
        rows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        wins: dict[str, int] = defaultdict(int)
        for seed in range(seeds):
            sc = generate(seed, engineers, jobs, preset)
            res = {a: allocate(sc, Weights(), a).metrics for a in ALGORITHMS}
            best = min(m["objective"] for m in res.values())
            for a, m in res.items():
                wins[a] += m["objective"] <= best + 1e-6
                for k, _ in COLUMNS:
                    rows[a][k].append(m[k])
        print(f"\n#### {PRESETS[preset].label}\n")
        print("| Strategy | " + " | ".join(t for _, t in COLUMNS) + " | Lowest cost |")
        print("|---" * (len(COLUMNS) + 2) + "|")
        out[preset] = {}
        for a in ALGORITHMS:
            means = {k: statistics.fmean(rows[a][k]) for k, _ in COLUMNS}
            out[preset][a] = means | {"wins": wins[a]}
            cells = [f"{means[k]:.1f}" for k, _ in COLUMNS]
            print(f"| {a} | " + " | ".join(cells) + f" | {wins[a]}/{seeds} |")
    return out


def gaps_full(seeds: int, engineers: int, jobs: int) -> dict[str, dict[str, dict[str, float]]]:
    """Gap to the proven optimum on full-size shifts, per preset. Any negative gap would mean
    the "optimum" isn't one, so it fails loudly instead of printing a flattering table.
    Returns {preset: {strategy: {"mean_gap_pct", "worst_gap_pct", "optimal_in"}}} plus an "all" key."""
    print("\n| Preset | Strategy | Mean gap % | Worst gap % | Optimal in |\n|---|---|---|---|---|")
    overall: dict[str, list[float]] = defaultdict(list)
    exact_s, columns = [], []
    out: dict[str, dict[str, dict[str, float]]] = {}
    for preset in PRESETS:
        per: dict[str, list[float]] = defaultdict(list)
        out[preset] = {}
        for seed in range(seeds):
            sc = generate(seed, engineers, jobs, preset)
            p = Planner(sc, Weights())
            t0 = time.perf_counter()
            run_exact(p)
            exact_s.append(time.perf_counter() - t0)
            columns.append(p.meta["solver"]["columns"])
            opt = p.total_cost()
            for a, (_, fn) in ALGORITHMS.items():
                q = Planner(sc, Weights())
                fn(q)
                g = 100 * (q.total_cost() - opt) / abs(opt)
                assert g > -1e-6, f"{a} beat the 'optimum' on {preset} seed {seed}: {g:.4f}%"
                per[a].append(g)
                overall[a].append(g)
        for a in ALGORITHMS:
            hits = sum(g < 0.01 for g in per[a])
            out[preset][a] = {
                "mean_gap_pct": statistics.fmean(per[a]),
                "worst_gap_pct": max(per[a]),
                "optimal_in": hits,
            }
            print(
                f"| {PRESETS[preset].label} | {a} | {statistics.fmean(per[a]):.2f} | {max(per[a]):.2f} | {hits}/{seeds} |"
            )
    print("\n| Strategy | Mean gap % (all presets) | Worst gap % | Optimal in |\n|---|---|---|---|")
    out["all"] = {}
    for a in ALGORITHMS:
        g = overall[a]
        hits = sum(x < 0.01 for x in g)
        out["all"][a] = {"mean_gap_pct": statistics.fmean(g), "worst_gap_pct": max(g), "optimal_in": hits}
        print(f"| {a} | {statistics.fmean(g):.2f} | {max(g):.2f} | {hits}/{len(g)} |")
    print(
        f"\nExact solve (enumerate + MILP): mean {statistics.fmean(exact_s):.1f} s, max {max(exact_s):.1f} s; "
        f"{statistics.fmean(columns):,.0f} routes per shift on average."
    )
    return out


def gaps(seeds: int, engineers: int = 4, jobs: int = 12) -> dict[str, dict[str, float]]:
    """Gap to the proven optimum on small shifts (the in-app "Measure gaps" study):
    {strategy: {"mean_gap_pct", "worst_gap_pct", "optimal_in"}}."""
    per: dict[str, list[float]] = defaultdict(list)
    worst: dict[str, float] = defaultdict(float)
    optimal_hits: dict[str, int] = defaultdict(int)
    for seed in range(seeds):
        sc = generate(seed, engineers, jobs, "normal")
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
    out = {}
    for a in ALGORITHMS:
        out[a] = {"mean_gap_pct": statistics.fmean(per[a]), "worst_gap_pct": worst[a], "optimal_in": optimal_hits[a]}
        print(f"| {a} | {statistics.fmean(per[a]):.2f} | {worst[a]:.2f} | {optimal_hits[a]}/{seeds} |")
    return out


SCALING_SIZES = [(14, 45), (30, 100), (60, 200)]


def scaling(sizes: list[tuple[int, int]] = SCALING_SIZES) -> dict[str, dict[str, float]]:
    """Solve time per strategy and size: {"14x45": {strategy: ms}}."""
    print("\n| Size | " + " | ".join(ALGORITHMS) + " |\n|---" * 1 + "|---" * len(ALGORITHMS) + "|")
    out = {}
    for e, j in sizes:
        sc = generate(1, e, j, "normal")
        out[f"{e}x{j}"] = {}
        for a in ALGORITHMS:
            t0 = time.perf_counter()
            allocate(sc, Weights(), a)
            out[f"{e}x{j}"][a] = (time.perf_counter() - t0) * 1000
        print(f"| {e} engineers, {j} jobs | " + " | ".join(f"{ms:.0f}" for ms in out[f"{e}x{j}"].values()) + " |")
    return out


def budgets(seeds: int = 6, engineers: int = 14, jobs: int = 45) -> list[dict[str, float | str]]:
    """Cost of each extra iteration: where the quality curve flattens is the budget to ship.
    Returns one row per (solver, iterations): {"solver", "iterations", "cost_below_regret_pct", "mean_ms"}."""
    from app.algorithms.alns import run_alns
    from app.algorithms.pyvrp_ils import run_pyvrp
    from app.algorithms.regret import run_regret

    scs = [generate(s, engineers, jobs, p) for s in range(seeds) for p in ("normal", "excursion")]

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
    print("\n| Solver | Iterations | Cost below regret-2 | Mean solve ms |\n|---|---|---|---|")
    rows: list[dict[str, float | str]] = []
    for name, fn, its in (("ALNS", run_alns, (100, 300, 600)), ("PyVRP", run_pyvrp, (250, 1000, 3000))):
        for it in its:
            c, t = run(lambda p, fn=fn, it=it: fn(p, max_iterations=it, runtime_s=60))
            rows.append(
                {"solver": name, "iterations": it, "cost_below_regret_pct": 100 * (base - c) / base, "mean_ms": t}
            )
            print(f"| {name} | {it} | {100 * (base - c) / base:.1f}% | {t:.0f} |")
    return rows


def _size(text: str) -> tuple[int, int]:
    e, j = text.lower().split("x")
    return int(e), int(j)


def main(argv: list[str] | None = None) -> dict[str, object]:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--engineers", type=int, default=14)
    ap.add_argument("--jobs", type=int, default=45)
    ap.add_argument("--gap-seeds", type=int, default=20)
    ap.add_argument("--gap-size", type=_size, default=(4, 12), help="engineers x jobs for the small-shift gap study")
    ap.add_argument(
        "--scaling-sizes",
        default=",".join(f"{e}x{j}" for e, j in SCALING_SIZES),
        help="comma-separated engineers x jobs for the solve-time table",
    )
    ap.add_argument("--budget-seeds", type=int, default=6, help="seeds per preset in the iteration-budget study")
    ap.add_argument("--only", choices=["quality", "gaps", "gaps-full", "scaling", "budgets"], help="run one study")
    args = ap.parse_args(argv)
    results: dict[str, object] = {}
    if args.only == "gaps-full":
        print(f"### Optimality gap at full size ({args.gap_seeds} shifts per preset, {args.engineers} x {args.jobs})")
        results["gaps_full"] = gaps_full(args.gap_seeds, args.engineers, args.jobs)
        return results
    if args.only in (None, "quality"):
        print(f"### Quality ({args.seeds} seeds per preset, {args.engineers} engineers, {args.jobs} jobs)")
        results["quality"] = quality(args.seeds, args.engineers, args.jobs)
    if args.only in (None, "gaps"):
        ge, gj = args.gap_size
        print(f"\n### Optimality gap ({args.gap_seeds} shifts of {ge} engineers x {gj} jobs, exact MILP optimum)")
        results["gaps"] = gaps(args.gap_seeds, ge, gj)
    if args.only in (None, "scaling"):
        print("\n### Solve time (ms, one shift)")
        results["scaling"] = scaling([_size(x) for x in args.scaling_sizes.split(",") if x])
    if args.only in (None, "budgets"):
        print(f"\n### Iteration budget ({2 * args.budget_seeds} shifts)")
        results["budgets"] = budgets(args.budget_seeds, args.engineers, args.jobs)
    return results


if __name__ == "__main__":
    main()
