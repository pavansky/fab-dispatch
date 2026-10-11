"""Repair-history retrieval: determinism, relevance, and the prediction API."""

import random

from fastapi.testclient import TestClient

from app.fabs import all_profiles, get_profile
from app.knowledge import (
    OBSERVATION_RATE,
    HashEmbedder,
    cause_observations,
    draw_fault,
    fault_symptom,
    synthetic_history,
)
from app.main import app
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("viewer"))


def test_history_is_reproducible_and_covers_every_family_of_every_fab():
    for profile in all_profiles().values():
        a, b = synthetic_history(profile, 300), synthetic_history(profile, 300)
        assert a == b
        assert {r.family for r in a} == set(profile.family_ids)


def _causes(profile, r):
    return profile.family(r.family).faults[r.code].causes


def test_symptoms_point_to_the_root_cause_only_sometimes():
    """A share of reports carries an observation of the true cause, none of another cause,
    and the generic part of the symptom is shared by every cause of the code."""
    for profile in all_profiles().values():
        history = synthetic_history(profile, 1500)
        own = 0
        for r in history:
            for c in _causes(profile, r):
                if c.cause != r.cause:
                    assert not any(o in r.symptom for o in cause_observations(c)), r
            own += any(o in r.symptom for c in _causes(profile, r) if c.cause == r.cause for o in cause_observations(c))
        assert abs(own / len(history) - OBSERVATION_RATE) < 0.05
        # Without an observation, the text says nothing about the cause: every generic symptom
        # of a fault code shows up under every one of its causes.
        seen = set()
        for r in history:
            base = next(s for s in profile.family(r.family).faults[r.code].symptoms if r.symptom.startswith(s))
            seen.add((r.family, r.code, base, r.cause))
        for f in profile.families:
            for code, fault in f.faults.items():
                assert {(f.id, code, s, c.cause) for s in fault.symptoms for c in fault.causes} <= seen


def test_live_tool_downs_carry_the_same_signal_without_changing_the_generator_stream():
    profile = get_profile("fab1-300mm-logic")
    rng, old = random.Random(5), random.Random(5)
    shown = 0
    for _ in range(400):
        family = rng.choice(profile.family_ids)
        assert old.choice(profile.family_ids) == family
        code, cause, text, standard = draw_fault(rng, profile, family)
        # The pre-signal draw sequence: code, generic symptom, context suffix.
        faults = profile.family(family).faults
        assert old.choice(list(faults)) == code
        old.choice(faults[code].symptoms)
        old.choice(["", "a", "b", "c", "d"])
        assert rng.getstate() == old.getstate()
        assert cause in faults[code].causes and standard % 15 == 0
        shown += any(o in text for o in cause_observations(cause))
    assert 0.5 < shown / 400 < 0.7
    a, b = random.Random(9), random.Random(9)
    assert fault_symptom(a, profile, "etch") == fault_symptom(b, profile, "etch")


def test_retrieval_recovers_the_cause_better_than_chance():
    """Held-out repairs: the likely cause is right well above the 50% of guessing between two
    causes, but below 100%, since 40% of reports carry no cause signal."""
    from app.config import Settings
    from app.knowledge import RepairIndex

    idx = RepairIndex(Settings(env="test"))
    profile = get_profile("fab1-300mm-logic")
    test = synthetic_history(profile, 300, seed=99)
    right = sum(idx.similar(profile, r.family, r.symptom)["prediction"]["likely_cause"] == r.cause for r in test)
    assert 0.65 < right / len(test) < 0.9


def test_embedder_is_normalised_and_lexically_sensible():
    e = HashEmbedder()
    v = e.embed("RF reflected power high")
    assert abs(sum(x * x for x in v) - 1) < 1e-9

    def cos(a, b):
        return sum(x * y for x, y in zip(e.embed(a), e.embed(b)))

    assert cos("RF reflected power high", "RF reflected power high on chamber B") > cos(
        "RF reflected power high", "slurry flow alarm"
    )


def test_similar_repairs_stay_in_family_and_match_the_fault():
    body = client.post("/api/repairs/similar", json={"family": "cmp", "symptom": "slurry flow alarm"}).json()
    assert body["neighbours"], "no neighbours returned"
    assert all(n["code"] == "SLURRY" for n in body["neighbours"][:3])
    p = body["prediction"]
    assert p["p10"] <= p["minutes"] <= p["p90"]


def test_predict_durations_only_touches_tool_downs():
    sc = client.post("/api/scenario", json={"seed": 3, "n_engineers": 6, "n_jobs": 20}).json()
    assert sc["fab_id"] == "fab1-300mm-logic"
    out = client.post("/api/repairs/predict-durations", json=sc).json()
    changed = {c["job_id"] for c in out["changes"]}
    kinds = {j["id"]: j["kind"] for j in sc["jobs"]}
    assert changed and all(kinds[j] == "down" for j in changed)
    assert len(out["scenario"]["jobs"]) == 20


def test_unknown_family_is_rejected():
    assert client.post("/api/repairs/similar", json={"family": "magic", "symptom": "broken"}).status_code == 422


def test_locked_disk_index_falls_back_to_memory(tmp_path):
    """Two processes can't share an embedded on-disk Qdrant folder; the second must not 500."""
    from app.config import Settings
    from app.knowledge import RepairIndex

    s = Settings(env="local", qdrant_path=str(tmp_path / "q"))
    first = RepairIndex(s)
    second = RepairIndex(s)  # same folder, already locked by `first`
    assert first.mode == "qdrant-disk"
    assert second.mode == "qdrant-memory"
    from app.fabs import get_profile

    assert second.similar(get_profile("fab1-300mm-logic"), "etch", "RF reflected power high")["prediction"]


def test_exact_search_is_the_default_and_agrees_with_qdrant(tmp_path):
    """No Qdrant configured: exact NumPy search. Both backends score neighbours identically;
    the exact one also breaks ties by repair id, so its answer is reproducible."""
    from app.config import Settings
    from app.fabs import get_profile
    from app.knowledge import RepairIndex

    exact = RepairIndex(Settings(env="test"))
    qdrant = RepairIndex(Settings(env="local", qdrant_path=str(tmp_path / "q")))
    assert exact.mode == "exact" and qdrant.mode == "qdrant-disk"
    profile = get_profile("fab1-300mm-logic")
    for symptom in ("RF reflected power high on chamber B", "endpoint signal drifting during production lot"):
        a = exact.backend.search(profile, "etch", symptom, 12)
        b = qdrant.backend.search(profile, "etch", symptom, 12)
        assert [round(x, 4) for x, _ in a] == [round(x, 4) for x, _ in b]
    first = exact.similar(profile, "etch", "RF reflected power high")
    assert first == exact.similar(profile, "etch", "RF reflected power high")


def test_a_symptom_with_nothing_in_common_gets_no_prediction():
    """Neighbours scoring 0 or less share nothing with the symptom and are dropped. (Tested on
    the scores directly: with a hashed embedding, any made-up word can collide with a history
    n-gram and score slightly above 0.)"""
    from app.config import Settings
    from app.fabs import get_profile
    from app.knowledge import RepairIndex

    idx = RepairIndex(Settings(env="test"))
    profile = get_profile("fab1-300mm-logic")
    unrelated = [(0.0, p) for _, p in idx.backend.search(profile, "etch", "RF reflected power high", 12)]
    idx.backend.search = lambda *a: unrelated
    assert idx.similar(profile, "etch", "anything") == {"neighbours": [], "prediction": None}
