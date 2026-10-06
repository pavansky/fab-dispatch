"""How good are the repair-time estimates? A held-out test of every way the app can predict one.

    python -m scripts.duration_study out/durations   # writes .log and .json

Train on each fab's repair history (1,800 repairs, seed 2026); test on 600 fresh repairs drawn
from the same fault catalogues with another seed, so nothing in the test set was seen. Compared:

* standard  - the fault code's standard estimate the planner uses today
* code mean - the empirical mean of that fault code in the history (a lookup table)
* k-NN      - the app's repair-history retrieval (similarity-weighted mean, neighbour p90)
* quantile  - gradient-boosted trees with quantile loss (P50 and P90), on family, code and symptom
* oracle    - knows the true root cause; the best any model could do without seeing the repair

Reported: MAE of the point estimate, how often the actual repair ran past the planned figure,
and P90 coverage (share of repairs finished within the P90; 90% is calibrated).
"""

import json
import statistics
import sys
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from app.config import get_settings
from app.fabs import all_profiles
from app.knowledge import RepairIndex, synthetic_history

OUT = sys.argv[1] if len(sys.argv) > 1 else "out/durations"
TEST_SEED, TEST_N = 99, 600
SUFFIXES = ["chamber A", "chamber B", "after PM", "production lot", "intermittently"]


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def features(repairs, families, codes):
    rows = []
    for r in repairs:
        rows.append([families.index(r.family), codes.index(r.code), *(int(s in r.symptom) for s in SUFFIXES)])
    return np.array(rows, dtype=float)


def summarise(actual, p50, p90=None):
    a, m = np.array(actual, float), np.array(p50, float)
    out = {
        "mae_min": round(float(np.mean(np.abs(a - m))), 1),
        "overrun_pct": round(float(np.mean(a > m)) * 100, 1),
    }
    if p90 is not None:
        q = np.array(p90, float)
        out["p90_coverage_pct"] = round(float(np.mean(a <= q)) * 100, 1)
        out["p90_mean_min"] = round(float(np.mean(q)), 1)
    return out


def study(profile, index):
    train = synthetic_history(profile)
    test = synthetic_history(profile, n=TEST_N, seed=TEST_SEED)
    families = profile.family_ids
    codes = sorted({c for f in families for c in profile.family(f).faults})
    actual = [r.minutes for r in test]

    def standard(r):
        causes = profile.family(r.family).faults[r.code].causes
        return round(statistics.fmean(c.mean_min for c in causes) / 15) * 15

    by_code: dict[str, list[int]] = {}
    for r in train:
        by_code.setdefault(r.code, []).append(r.minutes)

    def cause_mean(r):
        return next(c.mean_min for c in profile.family(r.family).faults[r.code].causes if c.cause == r.cause)

    def cause_p90(r):
        c = next(c for c in profile.family(r.family).faults[r.code].causes if c.cause == r.cause)
        return c.mean_min + 1.2816 * c.sd_min

    knn = [index.similar(profile, r.family, r.symptom)["prediction"] for r in test]
    knn_p50 = [p["minutes"] if p else standard(r) for p, r in zip(knn, test, strict=True)]
    knn_p90 = [p["p90"] if p else standard(r) for p, r in zip(knn, test, strict=True)]

    X, Xt = features(train, families, codes), features(test, families, codes)
    y = np.array([r.minutes for r in train], float)
    cat = [True, True] + [False] * len(SUFFIXES)
    gbm = {
        q: HistGradientBoostingRegressor(
            loss="quantile", quantile=q, max_iter=300, categorical_features=cat, random_state=0
        )
        .fit(X, y)
        .predict(Xt)
        for q in (0.5, 0.9)
    }

    return {
        "fab": profile.id,
        "train": len(train),
        "test": len(test),
        "spread_within_code_min": round(statistics.fmean(statistics.pstdev(v) for v in by_code.values()), 1),
        "methods": {
            "standard": summarise(actual, [standard(r) for r in test]),
            "code_mean": summarise(
                actual,
                [statistics.fmean(by_code[r.code]) for r in test],
                [float(np.quantile(by_code[r.code], 0.9)) for r in test],
            ),
            "knn": summarise(actual, knn_p50, knn_p90),
            "quantile_gbm": summarise(actual, gbm[0.5], gbm[0.9]),
            "oracle_cause": summarise(actual, [cause_mean(r) for r in test], [cause_p90(r) for r in test]),
        },
    }


def main():
    index = RepairIndex(get_settings())
    report = []
    for profile in all_profiles().values():
        res = study(profile, index)
        report.append(res)
        log(f"{res['fab']}: within-code spread {res['spread_within_code_min']} min")
        for name, m in res["methods"].items():
            log(f"  {name:13s} {m}")
    with open(OUT + ".json", "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
