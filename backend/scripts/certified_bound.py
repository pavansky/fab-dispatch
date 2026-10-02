"""Certified bounds on the optimum at sizes the exact solver can't prove in time.

    python -m scripts.certified_bound 30 100 0 out/cg_30x100_s0   # writes .log and .json


1. Enumerate every feasible route (same code as the exact solver).
2. Restricted master LP over a small column set (each heuristic's routes): solve, read duals.
3. Price ALL routes at once (reduced cost = cost - A^T duals, one sparse mat-vec); add the most
   negative; repeat until none is negative. The final LP value is a LOWER BOUND on any plan.
4. Integer solve over the generated columns gives a real plan (UPPER BOUND).
Every heuristic's gap to the lower bound is then a certified maximum gap to the optimum.
"""

import json
import sys
import time

import highspy
import numpy as np
from scipy.sparse import csc_matrix

from app.algorithms import ALGORITHMS, exact
from app.generator import generate
from app.models import Weights
from app.planner import Planner

E, J, SEED, OUT = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


exact.MAX_ROUTES = 10**9
sc = generate(SEED, E, J, "normal")
w = Weights()
log(f"size {E}x{J} seed {SEED}")
heur = {}
for a, (_, fn) in ALGORITHMS.items():
    q = Planner(sc, w)
    t = time.perf_counter()
    fn(q)
    heur[a] = {"cost": q.total_cost(), "seconds": time.perf_counter() - t, "routes": q.snapshot()}
    log(f"heuristic {a}: cost {heur[a]['cost']:.2f} in {heur[a]['seconds']:.2f}s")

p = Planner(sc, w)
jobs = p.unplaced()
ji = {j: i for i, j in enumerate(jobs)}
techs = list(p.techs)
m = E + len(jobs)
t0 = time.perf_counter()
cost, start, index, key = [], [0], [], {}
for k, tid in enumerate(techs):
    for s, (c, seq) in exact.enumerate_routes(p, tid).items():
        key[(tid, s)] = len(cost)
        cost.append(c)
        index.append(k)
        index.extend(E + ji[j] for j in seq)
        start.append(len(index))
    if (k + 1) % 5 == 0 or k + 1 == E:
        log(f"enumerated {k + 1}/{E} engineers: {len(cost):,} routes, {time.perf_counter() - t0:.0f}s")
n = len(cost)
c = np.array(cost)
A = csc_matrix((np.ones(len(index)), np.array(index), np.array(start)), shape=(m, n))
del cost, index, start
reward = sum(w.priority_reward * j.priority for j in p.open_jobs.values())

# initial columns: every heuristic's routes, plus each engineer's empty route
cols = set()
for h in heur.values():
    for tid, route in h["routes"].items():
        if route and (tid, frozenset(route)) in key:
            cols.add(key[(tid, frozenset(route))])
for tid in techs:
    cols.add(key[(tid, frozenset())])
del key


def solve(colset, integer=False, time_limit=None):
    idx = np.array(sorted(colset))
    sub = A[:, idx]
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = len(idx), m
    lp.col_cost_ = c[idx]
    lp.col_lower_ = np.zeros(len(idx))
    # No explicit x <= 1: each route uses its engineer's row (<= 1), which implies it. An explicit
    # bound would let in-model columns sit at 1 with negative reduced cost and stall pricing.
    lp.col_upper_ = np.ones(len(idx)) if integer else np.full(len(idx), highspy.kHighsInf)
    lp.row_lower_ = np.full(m, -highspy.kHighsInf)
    lp.row_upper_ = np.ones(m)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = sub.indptr.astype(np.int32)
    lp.a_matrix_.index_ = sub.indices.astype(np.int32)
    lp.a_matrix_.value_ = sub.data
    if integer:
        lp.integrality_ = [highspy.HighsVarType.kInteger] * len(idx)
    hs = highspy.Highs()
    hs.setOptionValue("output_flag", False)
    hs.setOptionValue("mip_rel_gap", 0.0)
    if time_limit:
        hs.setOptionValue("time_limit", float(time_limit))
    hs.passModel(lp)
    hs.run()
    info = hs.getInfo()
    return hs, info, idx


it = 0
t1 = time.perf_counter()
while True:
    it += 1
    hs, info, idx = solve(cols)
    y = np.array(hs.getSolution().row_dual)
    rc = c - A.T @ y
    rc[idx] = 0.0  # price only routes not yet in the master
    neg = np.flatnonzero(rc < -1e-7)
    log(
        f"colgen iter {it}: LP {info.objective_function_value + reward:.3f}, columns {len(cols):,}, improving routes {len(neg):,}, min reduced cost {rc.min():.4f}"
    )
    if len(neg) == 0:
        break
    take = neg[np.argsort(rc[neg])[:5000]]
    cols.update(take.tolist())
lower = info.objective_function_value + reward
log(f"LP converged: certified lower bound {lower:.3f} after {it} iterations, {time.perf_counter() - t1:.0f}s")

hs, info, idx = solve(cols, integer=True, time_limit=3600)
upper = info.objective_function_value + reward
status = hs.modelStatusToString(hs.getModelStatus())
log(f"integer solve over {len(cols):,} generated columns: {status}, best plan {upper:.3f}")
gap_ub_lb = 100 * (upper - lower) / abs(lower)
log(
    f"best plan is within {gap_ub_lb:.3f}% of the certified lower bound"
    + (" (proven optimal)" if gap_ub_lb < 1e-6 else "")
)
report = {
    "size": f"{E}x{J}",
    "seed": SEED,
    "routes": n,
    "lower_bound": lower,
    "best_plan": upper,
    "best_plan_gap_to_bound_pct": gap_ub_lb,
    "colgen_iterations": it,
    "columns_generated": len(cols),
    "heuristics": {
        a: {
            "cost": h["cost"],
            "seconds": h["seconds"],
            "gap_to_best_pct": 100 * (h["cost"] - upper) / abs(upper),
            "max_gap_to_optimum_pct": 100 * (h["cost"] - lower) / abs(lower),
        }
        for a, h in heur.items()
    },
}
with open(OUT + ".json", "w") as f:
    json.dump(report, f, indent=1)
for a, r in report["heuristics"].items():
    log(
        f"| {a} | cost {r['cost']:.1f} | {r['gap_to_best_pct']:.2f}% above best plan | at most {r['max_gap_to_optimum_pct']:.2f}% above optimum | {r['seconds']:.1f}s |"
    )
