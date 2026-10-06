"""Can a learned dispatch policy compete with the solvers? Policy search, scored against proven optima.

    python -m scripts.learned_policy_study out/learned   # writes .log and .json

The policy is greedy dispatch whose job order is learned instead of hand-written: each job gets a
score w . phi(job) and jobs are dispatched highest score first, each to its cheapest feasible
engineer. phi = priority, window start, window end, window width, duration, certification level,
and how many engineers can do the job at all (scarcity). w is learned with the cross-entropy
method (a gradient-free policy-search RL method) to minimise total plan cost on 40 training shifts
the test never sees. The shift generator is the environment; reward = minus the plan's cost.

Test: 40 held-out shifts (10 per preset) solved to proven optimality; every strategy's gap to it.
"""

import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

# One thread per worker: HiGHS and BLAS otherwise each spawn a thread per core under the pool.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "out/learned"
E, J = 14, 45
TRAIN = [(p, 1000 + s) for p in ("normal", "litho_crunch", "excursion", "overstaffed") for s in range(10)]
TEST = [(p, s) for p in ("normal", "litho_crunch", "excursion", "overstaffed") for s in range(10)]
ITERS, POP, ELITE = 15, 32, 6
FEATURES = ["priority", "earliest", "latest", "window", "duration", "min_level", "scarcity"]


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def phi(p, job):
    feasible, _ = p.scan(job.id)
    return np.array(
        [
            job.priority,
            job.earliest / 600,
            job.latest / 600,
            (job.latest - job.earliest) / 600,
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
        if feasible:
            p.commit(feasible[0])
    return p.total_cost()


def cost_of(args):
    w, preset, seed = args
    from app.generator import generate
    from app.models import Weights
    from app.planner import Planner

    return learned_greedy(Planner(generate(seed, E, J, preset), Weights()), np.array(w))


def mean_cost(ex, w):
    return statistics.fmean(ex.map(cost_of, [(list(w), p, s) for p, s in TRAIN]))


def test_shift(args):
    w, preset, seed = args
    from app.algorithms import ALGORITHMS
    from app.algorithms.exact import run_exact
    from app.generator import generate
    from app.models import Weights
    from app.planner import Planner

    sc = generate(seed, E, J, preset)
    p = Planner(sc, Weights())
    run_exact(p)
    opt = p.total_cost()
    out = {}
    for a in ("greedy", "regret", "alns", "pyvrp"):
        q = Planner(sc, Weights())
        ALGORITHMS[a][1](q)
        out[a] = 100 * (q.total_cost() - opt) / abs(opt)
    out["learned"] = 100 * (learned_greedy(Planner(sc, Weights()), np.array(w)) - opt) / abs(opt)
    return out


def main():
    rng = np.random.default_rng(0)
    # Start from the hand-written rule (priority first, then deadline) so learning has to beat it.
    mu = np.array([10.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0])
    sigma = np.full(len(FEATURES), 3.0)
    curve = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        hand = mean_cost(ex, mu)
        log(f"hand-written rule on training shifts: {hand:.1f}")
        best_w, best = mu, hand
        for it in range(ITERS):
            pop = mu + sigma * rng.standard_normal((POP, len(FEATURES)))
            scores = np.array([mean_cost(ex, w) for w in pop])
            elite = pop[np.argsort(scores)[:ELITE]]
            mu, sigma = elite.mean(0), elite.std(0) + 0.1
            if scores.min() < best:
                best, best_w = float(scores.min()), pop[np.argmin(scores)]
            curve.append(round(best, 1))
            log(f"iter {it + 1:2d}: best training cost {best:.1f}")
        log("weights: " + ", ".join(f"{n} {v:+.2f}" for n, v in zip(FEATURES, best_w, strict=True)))
        rows = list(ex.map(test_shift, [(list(best_w), p, s) for p, s in TEST]))
    summary = {}
    for a in ("greedy", "learned", "regret", "alns", "pyvrp"):
        g = [r[a] for r in rows]
        summary[a] = {"mean_gap_pct": round(statistics.fmean(g), 2), "worst_gap_pct": round(max(g), 2)}
        log(f"{a:8s} mean gap {summary[a]['mean_gap_pct']:6.2f}%  worst {summary[a]['worst_gap_pct']:6.2f}%")
    d = np.array([r["greedy"] - r["learned"] for r in rows])
    b = np.random.default_rng(1)
    boots = [b.choice(d, len(d)).mean() for _ in range(5000)]
    ci = [round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)]
    log(f"learned vs hand-written greedy: {d.mean():.2f} gap points better, 95% CI {ci}")
    with open(OUT + ".json", "w") as f:
        json.dump(
            {
                "train_shifts": len(TRAIN),
                "test_shifts": len(TEST),
                "features": FEATURES,
                "weights": [round(float(v), 3) for v in best_w],
                "hand_rule_train_cost": round(hand, 1),
                "training_curve": curve,
                "test": summary,
                "learned_vs_greedy_gap_points": round(float(d.mean()), 2),
                "ci95": ci,
            },
            f,
            indent=1,
        )


if __name__ == "__main__":
    main()
