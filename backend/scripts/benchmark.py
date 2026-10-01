"""Compare algorithms over many seeded scenarios: python -m scripts.benchmark [--seeds 30]"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict

from app.algorithms import ALGORITHMS
from app.engine import allocate
from app.generator import PRESETS, generate
from app.models import Weights

COLUMNS = [
    ("coverage_pct", "Coverage %"),
    ("critical_coverage_pct", "Critical %"),
    ("priority_weighted_coverage_pct", "Priority-wtd %"),
    ("mean_response_min", "Response min"),
    ("walk_m_per_job", "Walk m/job"),
    ("wait_min_total", "Wait min"),
    ("workload_std", "Load std"),
    ("objective", "Objective ↓"),
    ("runtime_ms", "Runtime ms"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--engineers", type=int, default=14)
    ap.add_argument("--jobs", type=int, default=45)
    args = ap.parse_args()

    for preset in PRESETS:
        rows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        wins: dict[str, int] = defaultdict(int)
        for seed in range(args.seeds):
            sc = generate(seed, args.engineers, args.jobs, preset)
            results = {a: allocate(sc, Weights(), a).metrics for a in ALGORITHMS}
            best = min(r["objective"] for r in results.values())
            for a, m in results.items():
                wins[a] += m["objective"] <= best + 1e-6
                for k, _ in COLUMNS:
                    rows[a][k].append(m[k])
        print(f"\n### {PRESETS[preset].label} ({args.seeds} seeds, {args.engineers} engineers, {args.jobs} jobs)\n")
        print("| Algorithm | " + " | ".join(t for _, t in COLUMNS) + " | Best objective |")
        print("|---" * (len(COLUMNS) + 2) + "|")
        for a in ALGORITHMS:
            cells = [f"{statistics.fmean(rows[a][k]):.1f}" for k, _ in COLUMNS]
            print(f"| {a} | " + " | ".join(cells) + f" | {wins[a]}/{args.seeds} |")


if __name__ == "__main__":
    main()
