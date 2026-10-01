"""Repair-history retrieval: determinism, relevance, and the prediction API."""
from fastapi.testclient import TestClient

from app.knowledge import CATALOG, HashEmbedder, synthetic_history
from app.main import app

client = TestClient(app)


def test_history_is_reproducible_across_processes():
    a, b = synthetic_history(200), synthetic_history(200)
    assert a == b
    assert {r.family for r in a} == set(CATALOG)


def test_embedder_is_normalised_and_lexically_sensible():
    e = HashEmbedder()
    v = e.embed("RF reflected power high")
    assert abs(sum(x * x for x in v) - 1) < 1e-9
    def cos(a, b):
        return sum(x * y for x, y in zip(e.embed(a), e.embed(b)))
    assert cos("RF reflected power high", "RF reflected power high on chamber B") > cos("RF reflected power high", "slurry flow alarm")


def test_similar_repairs_stay_in_family_and_match_the_fault():
    body = client.post("/api/repairs/similar", json={"family": "cmp", "symptom": "slurry flow alarm"}).json()
    assert body["neighbours"], "no neighbours returned"
    assert all(n["code"] == "SLURRY" for n in body["neighbours"][:3])
    p = body["prediction"]
    assert p["p10"] <= p["minutes"] <= p["p90"]


def test_predict_durations_only_touches_tool_downs():
    sc = client.post("/api/scenario", json={"seed": 3, "n_engineers": 6, "n_jobs": 20}).json()
    out = client.post("/api/repairs/predict-durations", json=sc).json()
    changed = {c["job_id"] for c in out["changes"]}
    kinds = {j["id"]: j["kind"] for j in sc["jobs"]}
    assert changed and all(kinds[j] == "down" for j in changed)
    assert len(out["scenario"]["jobs"]) == 20


def test_unknown_family_is_rejected():
    assert client.post("/api/repairs/similar", json={"family": "magic", "symptom": "broken"}).status_code == 422
