"""Can a learned dispatch order compete with the solvers? Black-box policy search, scored against proven optima.

    python -m scripts.learned_policy_study out/learned           # 5 CEM seeds; writes .log and .json
    python -m scripts.learned_policy_study out/learned --quick   # 1 seed, 4+4 shifts, short search

The policy is greedy dispatch whose job order is learned instead of hand-written: each job gets a
score w . phi(job) and jobs are dispatched highest score first, each to its cheapest feasible
engineer, committed only if that insertion lowers the plan's total cost (Planner.total_cost(), the
objective every strategy is scored on). phi = priority, window start, window end, duration,
certification level, and scarcity (1 / (1 + engineers who can do the job)). Window width is left
out: it is window end - window start, so any weight on it folds into the other two and would only
make the learned weights unidentifiable.

w is found by black-box policy search with the cross-entropy method (CEM): sample weight vectors
around a mean, keep the elite (lowest mean total cost on 40 training shifts the test never sees),
refit the mean and spread to them, repeat. It starts from the hand-written rule (priority first,
then deadline). The search is randomised, so it runs with 5 seeds (independent CEM runs).

Test: 40 held-out shifts (10 per preset), each solved to proven optimality once; the optimum is
cached in <out dir>/exact_optima.json, keyed by a hash of the shift, the weights and the planner and
solver source, so re-runs (other seeds or settings) don't re-solve and a changed planner does.
Reported: every strategy's mean and worst gap to the optimum; the learned policy's mean test gap
per seed and its mean, SD, min and max across seeds (search randomness); and, for the best and the
median seed by training cost (chosen without looking at the test), a paired bootstrap 95% CI over
test shifts of the gap points gained against the hand-written rule (same greedy and commit rule,
starting weights, so it isolates the learned order) and against the registry's greedy. A CI covers
test-shift variation for that one seed only; the across-seed spread is the other half.
"""

import argparse
import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

# One thread per worker: HiGHS and BLAS otherwise each spawn a thread per core under the pool.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

E, J = 14, 45
PRESETS = ("normal", "litho_crunch", "excursion", "overstaffed")
FEATURES = ["priority", "earliest", "latest", "duration", "min_level", "scarcity"]
HAND_RULE = [10.0, 0.0, -1.0, 0.0, 0.0, 0.0]  # priority first, then the earliest deadline
SOLVERS = ("greedy", "regret", "alns", "pyvrp")
OUT = "out/learned"


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


@lru_cache(maxsize=256)
def shift(preset, seed):
    from app.generator import generate

    return generate(seed, E, J, preset)


def phi(p, job):
    feasible, _ = p.scan(job.id)
    return np.array(
        [
            job.priority,
            job.earliest / 600,
            job.latest / 600,
            job.duration / 120,
            job.min_level,
            1 / (1 + len(feasible)),
        ]
    )


def learned_greedy(p, w):
    jobs = [p.jobs[j] for j in p.unplaced()]
    feats = {j.id: phi(p, j) for j in jobs}
    for job in sorted(jobs, key=lambda j: (-(w @ feats[j.id]), j.id)):
        feasible, _ = p.scan(job.id)
        if feasible and feasible[0].cost < 0:  # only insertions that lower the total cost
            p.commit(feasible[0])
    return p.total_cost()


def cost_of(args):
    w, preset, seed = args
    from app.models import Weights
    from app.planner import Planner

    return learned_greedy(Planner(shift(preset, seed), Weights()), np.array(w))


def shift_key(preset, seed):
    """Changes when the shift, the weights or the planner/solver code change."""
    import app.algorithms.exact as exact
    import app.planner as planner
    from app.models import Weights

    h = hashlib.sha256(shift(preset, seed).model_dump_json().encode())
    h.update(Weights().model_dump_json().encode())
    for mod in (planner, exact):
        h.update(Path(mod.__file__).read_bytes())
    return h.hexdigest()[:16]


def solve_exact(args):
    preset, seed = args
    from app.algorithms.exact import run_exact
    from app.models import Weights
    from app.planner import Planner

    t = time.perf_counter()
    p = Planner(shift(preset, seed), Weights())
    run_exact(p)
    return p.total_cost(), round(time.perf_counter() - t, 1)


def solver_costs(args):
    preset, seed = args
    from app.algorithms import ALGORITHMS
    from app.models import Weights
    from app.planner import Planner

    out = {}
    for a in SOLVERS:
        q = Planner(shift(preset, seed), Weights())
        ALGORITHMS[a][1](q)
        out[a] = q.total_cost()
    return out


def optima(ex, test, path):
    """Exact optimum per test shift, from the cache when its key still matches."""
    cache = json.loads(path.read_text()) if path.exists() else {}
    keys = {(p, s): shift_key(p, s) for p, s in test}
    todo = [(p, s) for p, s in test if cache.get(f"{p}-{s}", {}).get("key") != keys[(p, s)]]
    log(f"exact optima: {len(test) - len(todo)} cached, solving {len(todo)}")
    for (p, s), (opt, secs) in zip(todo, ex.map(solve_exact, todo), strict=True):
        cache[f"{p}-{s}"] = {"key": keys[(p, s)], "optimum": opt, "solve_s": secs}
        path.write_text(json.dumps(cache, indent=1, sort_keys=True))  # keep progress if interrupted
    return {(p, s): cache[f"{p}-{s}"]["optimum"] for p, s in test}


def cem(ex, train, seed, iters, pop, elite):
    rng = np.random.default_rng(seed)
    mu, sigma = np.array(HAND_RULE), np.full(len(FEATURES), 3.0)

    def mean_costs(ws):
        costs = list(ex.map(cost_of, [(list(w), p, s) for w in ws for p, s in train], chunksize=16))
        return np.array(costs).reshape(len(ws), len(train)).mean(1)

    best_w, best = mu, float(mean_costs([mu])[0])
    curve = []
    for it in range(iters):
        cand = mu + sigma * rng.standard_normal((pop, len(FEATURES)))
        scores = mean_costs(cand)
        top = cand[np.argsort(scores)[:elite]]
        mu, sigma = top.mean(0), top.std(0) + 0.1
        if scores.min() < best:
            best, best_w = float(scores.min()), cand[np.argmin(scores)]
        curve.append(round(best, 1))
        log(f"  seed {seed} iter {it + 1:2d}: best training cost {best:.1f}")
    return best_w, best, curve


def gaps(costs, opt):
    return [100 * (c - o) / abs(o) for c, o in zip(costs, opt, strict=True)]


def paired_ci(base, other, seed=1):
    """Mean of base - other (gap points gained) and its paired bootstrap 95% CI."""
    d = np.array(base) - np.array(other)
    b = np.random.default_rng(seed)
    boots = [b.choice(d, len(d)).mean() for _ in range(5000)]
    return round(float(d.mean()), 2), [round(float(np.percentile(boots, q)), 2) for q in (2.5, 97.5)]


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=OUT, help="output path prefix (.log and .json are added)")
    ap.add_argument("--quick", action="store_true", help="1 seed, 4 training and 4 test shifts, short search")
    ap.add_argument("--seeds", type=int, help="independent CEM runs (default 5; 1 with --quick)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    OUT = args.out
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    per_preset = 1 if args.quick else 10
    n_seeds = args.seeds or (1 if args.quick else 5)
    iters, pop, elite = (2, 8, 3) if args.quick else (15, 32, 6)
    train = [(p, 1000 + s) for p in PRESETS for s in range(per_preset)]
    test = [(p, s) for p in PRESETS for s in range(per_preset)]
    log(
        f"black-box policy search (cross-entropy method): {n_seeds} seed(s), {len(train)} training / "
        f"{len(test)} test shifts, {iters} iterations x {pop} candidates"
    )

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        opt_by_shift = optima(ex, test, Path(OUT).parent / "exact_optima.json")
        opt = [opt_by_shift[t] for t in test]
        solved = list(ex.map(solver_costs, test))
        hand_train = statistics.fmean(ex.map(cost_of, [(HAND_RULE, p, s) for p, s in train]))
        log(f"hand-written rule on training shifts: {hand_train:.1f}")
        runs = []
        for seed in range(n_seeds):
            w, train_cost, curve = cem(ex, train, seed, iters, pop, elite)
            test_costs = list(ex.map(cost_of, [(list(w), p, s) for p, s in test]))
            g = gaps(test_costs, opt)
            runs.append(
                {
                    "seed": seed,
                    "weights": [round(float(v), 3) for v in w],
                    "train_cost": round(train_cost, 1),
                    "training_curve": curve,
                    "test_gaps": g,
                    "test_mean_gap_pct": round(statistics.fmean(g), 2),
                    "test_worst_gap_pct": round(max(g), 2),
                }
            )
            log(
                f"seed {seed}: train {train_cost:.1f}, test mean gap {runs[-1]['test_mean_gap_pct']:.2f}%, "
                "weights " + ", ".join(f"{n} {v:+.2f}" for n, v in zip(FEATURES, w, strict=True))
            )
        hand_gaps = gaps(list(ex.map(cost_of, [(HAND_RULE, p, s) for p, s in test])), opt)

    summary = {a: gaps([s[a] for s in solved], opt) for a in SOLVERS} | {"hand_rule": hand_gaps}
    test_summary = {
        a: {"mean_gap_pct": round(statistics.fmean(g), 2), "worst_gap_pct": round(max(g), 2)}
        for a, g in summary.items()
    }
    for a, s in test_summary.items():
        log(f"{a:9s} mean gap {s['mean_gap_pct']:6.2f}%  worst {s['worst_gap_pct']:6.2f}%")
    means = [r["test_mean_gap_pct"] for r in runs]
    across = {
        "mean_gap_pct": round(statistics.fmean(means), 2),
        "sd_gap_pct": round(statistics.stdev(means), 2) if len(means) > 1 else None,
        "min_gap_pct": round(min(means), 2),
        "max_gap_pct": round(max(means), 2),
    }
    log(f"learned, across {len(runs)} seed(s): {across}")
    by_train = sorted(runs, key=lambda r: r["train_cost"])
    picks = {"best_seed": by_train[0], "median_seed": by_train[(len(by_train) - 1) // 2]}
    paired = {}
    for label, r in picks.items():
        vs_hand, vs_hand_ci = paired_ci(hand_gaps, r["test_gaps"])
        vs_greedy, vs_greedy_ci = paired_ci(summary["greedy"], r["test_gaps"])
        paired[label] = {
            "seed": r["seed"],
            "vs_hand_rule_gap_points": vs_hand,
            "vs_hand_rule_ci95": vs_hand_ci,
            "vs_greedy_gap_points": vs_greedy,
            "vs_greedy_ci95": vs_greedy_ci,
        }
        log(
            f"{label} (seed {r['seed']}): {vs_hand:+.2f} gap points vs hand rule {vs_hand_ci}, "
            f"{vs_greedy:+.2f} vs greedy {vs_greedy_ci}"
        )
    with open(OUT + ".json", "w") as f:
        json.dump(
            {
                "method": "black-box policy search (cross-entropy method)",
                "quick": args.quick,
                "train_shifts": len(train),
                "test_shifts": len(test),
                "cem": {"seeds": n_seeds, "iterations": iters, "population": pop, "elite": elite},
                "features": FEATURES,
                "hand_rule_weights": HAND_RULE,
                "hand_rule_train_cost": round(hand_train, 1),
                "test": test_summary,
                "learned_per_seed": [{k: v for k, v in r.items() if k != "test_gaps"} for r in runs],
                "learned_across_seeds": across,
                "paired": paired,
            },
            f,
            indent=1,
        )


if __name__ == "__main__":
    main()
