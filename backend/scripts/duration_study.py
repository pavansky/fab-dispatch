"""How good are the repair-time estimates? A held-out test of every way the app can predict one.

    python -m scripts.duration_study out/durations           # writes .log and .json
    python -m scripts.duration_study out/durations --quick   # 150 test repairs per fab, smoke test

Train on each fab's repair history (1,800 repairs, seed 2026); test on 600 fresh repairs drawn
from the same fault catalogues with another seed, so nothing in the test set was seen. In the
history, 60% of symptoms carry an observation that points to the true root cause and 40% carry
none (app/knowledge.py), so the best any text model can do on the cause is about 80% (two causes
per code). Compared:

* catalogue  - catalogue estimate (true generator mean per fault code): the standard estimate the
               planner uses, i.e. the mean over the code's causes from the profile, rounded to
               15 min. It is the generator's own parameter, so no estimate built per fault code
               from data can beat it on average; a fab would not know it exactly.
* code_mean  - empirical fault-code mean from the training history (P10/P90 from the same code):
               the realistic baseline, a lookup table a fab could build from its CMMS.
* knn        - the app's repair-history retrieval (similarity-weighted mean, neighbours' P10/P90)
* classifier - logistic regression on the symptom's words and the code predicts the root cause;
               the estimate is the expected duration over the predicted causes (empirical
               per-cause times from training), with the P10/P90 of that mixture
* gbm        - gradient-boosted trees with quantile loss (P10, P50, P90) on family, code and the
               symptom's words
* oracle     - knows the true root cause (its catalogue mean, mean +- 1.28 sd); the best any model
               could do without seeing the repair

Reported per method: MAE of the point estimate, how often the actual repair ran past it, and two
separate interval checks: P10-P90 coverage (share of repairs inside the band; 80% is calibrated)
and P90 coverage (share finished by the P90; 90% is calibrated). Also: how often k-NN's and the
classifier's likely cause is the true cause, against chance and the ceiling the text allows, and
MAE split by whether the symptom carries a cause observation.
"""

import argparse
import json
import statistics
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression

from app.config import get_settings
from app.fabs import all_profiles
from app.knowledge import OBSERVATION_RATE, RepairIndex, cause_observations, standard_estimate, synthetic_history

TRAIN_SEED, TEST_SEED = 2026, 99
OUT = "out/durations"


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(OUT + ".log", "a") as f:
        f.write(line + "\n")


def summarise(actual, p50, p10=None, p90=None):
    a, m = np.array(actual, float), np.array(p50, float)
    out = {
        "mae_min": round(float(np.mean(np.abs(a - m))), 1),
        "overrun_pct": round(float(np.mean(a > m)) * 100, 1),
    }
    if p90 is not None:
        hi = np.array(p90, float)
        out["p90_coverage_pct"] = round(float(np.mean(a <= hi)) * 100, 1)
        out["p90_mean_min"] = round(float(np.mean(hi)), 1)
    if p10 is not None and p90 is not None:
        lo = np.array(p10, float)
        out["p10_p90_coverage_pct"] = round(float(np.mean((a >= lo) & (a <= hi))) * 100, 1)
        out["p10_p90_width_min"] = round(float(np.mean(hi - lo)), 1)
    return out


def weighted_quantile(values, weights, q):
    order = np.argsort(values)
    v, w = np.asarray(values, float)[order], np.asarray(weights, float)[order]
    cdf = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(cdf, q), len(v) - 1)])


def has_observation(profile, r):
    causes = profile.family(r.family).faults[r.code].causes
    return any(o in r.symptom for c in causes for o in cause_observations(c))


def study(profile, index, test_n, gbm_iters, train_n=None):
    train = (
        synthetic_history(profile, seed=TRAIN_SEED)
        if train_n is None
        else synthetic_history(profile, n=train_n, seed=TRAIN_SEED)
    )
    test = synthetic_history(profile, n=test_n, seed=TEST_SEED)
    families = profile.family_ids
    codes = sorted({c for f in families for c in profile.family(f).faults})
    actual = [r.minutes for r in test]
    n_causes = {(f, c): len(profile.family(f).faults[c].causes) for f in families for c in profile.family(f).faults}

    def causes_of(r):
        return profile.family(r.family).faults[r.code].causes

    by_code: dict[str, list[int]] = {}
    by_cause: dict[str, list[int]] = {}
    for r in train:
        by_code.setdefault(r.code, []).append(r.minutes)
        by_cause.setdefault(r.cause, []).append(r.minutes)

    # k-NN (the app). A symptom with no match falls back to the code mean.
    knn = [index.similar(profile, r.family, r.symptom)["prediction"] for r in test]
    fallback = sum(p is None for p in knn)

    def code_mean(r):
        return statistics.fmean(by_code[r.code])

    knn_p50 = [p["minutes"] if p else code_mean(r) for p, r in zip(knn, test, strict=True)]
    knn_p10 = [p["p10"] if p else np.quantile(by_code[r.code], 0.1) for p, r in zip(knn, test, strict=True)]
    knn_p90 = [p["p90"] if p else np.quantile(by_code[r.code], 0.9) for p, r in zip(knn, test, strict=True)]
    knn_cause = [p["likely_cause"] if p else None for p in knn]

    # Words of the symptom (+ a token for the code) for the classifier and the trees.
    def doc(r):
        return f"{r.symptom} code_{r.code.replace('-', '_')}"

    vec = CountVectorizer(token_pattern=r"[a-z0-9_]+", min_df=2, binary=True)
    W, Wt = vec.fit_transform([doc(r) for r in train]), vec.transform([doc(r) for r in test])

    # Classifier: P(cause | words), restricted to the code's own causes, then a mixture of the
    # empirical per-cause durations.
    clf = LogisticRegression(max_iter=3000, C=1.0).fit(W, [r.cause for r in train])
    proba = clf.predict_proba(Wt)
    col = {c: i for i, c in enumerate(clf.classes_)}
    clf_p50, clf_p10, clf_p90, clf_cause = [], [], [], []
    for r, pr in zip(test, proba, strict=True):
        names = [c.cause for c in causes_of(r) if c.cause in col and c.cause in by_cause]
        w = np.array([pr[col[c]] for c in names])
        w = w / w.sum() if w.sum() > 0 else np.full(len(names), 1 / len(names))
        clf_cause.append(names[int(np.argmax(w))])
        clf_p50.append(sum(wi * statistics.fmean(by_cause[c]) for wi, c in zip(w, names, strict=True)))
        vals = np.concatenate([by_cause[c] for c in names])
        wts = np.concatenate([np.full(len(by_cause[c]), wi / len(by_cause[c])) for wi, c in zip(w, names, strict=True)])
        clf_p10.append(weighted_quantile(vals, wts, 0.1))
        clf_p90.append(weighted_quantile(vals, wts, 0.9))

    # Quantile trees on family, code and the symptom's words.
    def tab(rows, words):
        ids = np.array([[families.index(r.family), codes.index(r.code)] for r in rows], float)
        return np.hstack([ids, words.toarray().astype(float)])

    X, Xt = tab(train, W), tab(test, Wt)
    y = np.array([r.minutes for r in train], float)
    cat = [True, True] + [False] * W.shape[1]
    gbm = {
        q: HistGradientBoostingRegressor(
            loss="quantile", quantile=q, max_iter=gbm_iters, categorical_features=cat, random_state=0
        )
        .fit(X, y)
        .predict(Xt)
        for q in (0.1, 0.5, 0.9)
    }

    def true_cause(r):
        return next(c for c in causes_of(r) if c.cause == r.cause)

    oracle = [true_cause(r) for r in test]
    observed = np.array([has_observation(profile, r) for r in test])
    chance = statistics.fmean(1 / n_causes[(r.family, r.code)] for r in test)
    ceiling = statistics.fmean(OBSERVATION_RATE + (1 - OBSERVATION_RATE) / n_causes[(r.family, r.code)] for r in test)

    def accuracy(guesses, mask=None):
        hits = np.array([g == r.cause for g, r in zip(guesses, test, strict=True)])
        return round(float(hits[mask].mean() if mask is not None else hits.mean()), 3)

    def split_mae(pred):
        err = np.abs(np.array(actual, float) - np.array(pred, float))
        return {
            "with_observation": round(float(err[observed].mean()), 1),
            "without_observation": round(float(err[~observed].mean()), 1),
        }

    code_p50 = [code_mean(r) for r in test]
    return {
        "fab": profile.id,
        "train": len(train),
        "test": len(test),
        "test_with_observation_pct": round(float(observed.mean()) * 100, 1),
        "knn_fallbacks": fallback,
        "spread_within_code_min": round(statistics.fmean(statistics.pstdev(v) for v in by_code.values()), 1),
        "methods": {
            "catalogue": summarise(actual, [standard_estimate(profile, r.family, r.code) for r in test]),
            "code_mean": summarise(
                actual,
                code_p50,
                [float(np.quantile(by_code[r.code], 0.1)) for r in test],
                [float(np.quantile(by_code[r.code], 0.9)) for r in test],
            ),
            "knn": summarise(actual, knn_p50, knn_p10, knn_p90),
            "classifier": summarise(actual, clf_p50, clf_p10, clf_p90),
            "gbm": summarise(actual, gbm[0.5], gbm[0.1], gbm[0.9]),
            "oracle_cause": summarise(
                actual,
                [c.mean_min for c in oracle],
                [c.mean_min - 1.2816 * c.sd_min for c in oracle],
                [c.mean_min + 1.2816 * c.sd_min for c in oracle],
            ),
        },
        "mae_by_observation": {
            "code_mean": split_mae(code_p50),
            "knn": split_mae(knn_p50),
            "classifier": split_mae(clf_p50),
        },
        "cause_recovery": {
            "chance": round(chance, 3),
            "ceiling": round(ceiling, 3),
            "knn": accuracy(knn_cause),
            "knn_with_observation": accuracy(knn_cause, observed),
            "knn_without_observation": accuracy(knn_cause, ~observed),
            "classifier": accuracy(clf_cause),
        },
    }


def main(argv=None):
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=OUT, help="output path prefix (.log and .json are added)")
    ap.add_argument("--quick", action="store_true", help="150 test repairs per fab and smaller trees")
    # Smoke-test sizes (tests/test_scripts.py); each overrides the study's or --quick's value.
    ap.add_argument("--train-n", type=int, help="training repairs per fab (default: the fab's full history)")
    ap.add_argument("--test-n", type=int, help="held-out test repairs per fab (default 600; 150 with --quick)")
    ap.add_argument("--gbm-iters", type=int, help="boosting iterations (default 300; 100 with --quick)")
    ap.add_argument("--fab", help="study one fab only (default: every profile)")
    args = ap.parse_args(argv)
    OUT = args.out
    test_n, gbm_iters = (150, 100) if args.quick else (600, 300)
    test_n, gbm_iters = args.test_n or test_n, args.gbm_iters or gbm_iters

    index = RepairIndex(get_settings())
    report = []
    profiles = all_profiles()
    if args.fab:
        profiles = {args.fab: profiles[args.fab]}
    for profile in profiles.values():
        res = study(profile, index, test_n, gbm_iters, args.train_n)
        report.append(res)
        log(
            f"{res['fab']}: within-code spread {res['spread_within_code_min']} min, "
            f"{res['test_with_observation_pct']}% of test symptoms carry a cause observation"
        )
        for name, m in res["methods"].items():
            log(f"  {name:13s} {m}")
        log(f"  cause recovery {res['cause_recovery']}")
        log(f"  MAE by observation {res['mae_by_observation']}")
    with open(OUT + ".json", "w") as f:
        json.dump({"quick": args.quick, "fabs": report}, f, indent=1)
    return report


if __name__ == "__main__":
    main()
