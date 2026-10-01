"""Benchmark every strategy; prints Markdown for docs/ANALYSIS.md.

    python -m scripts.benchmark --seeds 20

Three studies:
1. quality across the four scenario presets (mean over seeded shifts, lowest-cost wins)
2. optimality gap against the exact MILP on small shifts
3. runtime scaling with problem size
"""
from __future__ import annotations

import argparse
import statistics
import time
from collections import defaultdict

from app.algorithms import ALGORITHMS
from app.algorithms.exact import run_exact
from app.engine import allocate
from app.generator import PRESETS, generate
from app.models import Weights
from app.planner import Planner

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


def quality(seeds: int, engineers: int, jobs: int) -> None:
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
        for a in ALGORITHMS:
            cells = [f"{statistics.fmean(rows[a][k]):.1f}" for k, _ in COLUMNS]
            print(f"| {a} | " + " | ".join(cells) + f" | {wins[a]}/{seeds} |")


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


def scaling() -> None:
    print("\n| Size | " + " | ".join(ALGORITHMS) + " |\n|---" * 1 + "|---" * len(ALGORITHMS) + "|")
    for e, j in [(14, 45), (30, 100), (60, 200)]:
        sc = generate(1, e, j, "normal")
        cells = []
        for a in ALGORITHMS:
            t0 = time.perf_counter()
            allocate(sc, Weights(), a)
            cells.append(f"{(time.perf_counter() - t0) * 1000:.0f}")
        print(f"| {e} engineers, {j} jobs | " + " | ".join(cells) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--engineers", type=int, default=14)
    ap.add_argument("--jobs", type=int, default=45)
    ap.add_argument("--gap-seeds", type=int, default=20)
    args = ap.parse_args()
    print(f"### Quality ({args.seeds} seeds per preset, {args.engineers} engineers, {args.jobs} jobs)")
    quality(args.seeds, args.engineers, args.jobs)
    print(f"\n### Optimality gap ({args.gap_seeds} shifts of 4 engineers x 12 jobs, exact MILP optimum)")
    gaps(args.gap_seeds)
    print("\n### Solve time (ms, one shift)")
    scaling()


if __name__ == "__main__":
    main()
