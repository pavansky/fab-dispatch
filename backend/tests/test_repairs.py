"""Repair-history retrieval: determinism, relevance, and the prediction API."""

from fastapi.testclient import TestClient

from app.fabs import all_profiles
from app.knowledge import HashEmbedder, synthetic_history
from app.main import app
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("viewer"))


def test_history_is_reproducible_and_covers_every_family_of_every_fab():
    for profile in all_profiles().values():
        a, b = synthetic_history(profile, 300), synthetic_history(profile, 300)
        assert a == b
        assert {r.family for r in a} == set(profile.family_ids)


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
    from app.config import Settings
    from app.fabs import get_profile
    from app.knowledge import RepairIndex

    out = RepairIndex(Settings(env="test")).similar(get_profile("fab1-300mm-logic"), "etch", "zzqx")
    assert out == {"neighbours": [], "prediction": None}
