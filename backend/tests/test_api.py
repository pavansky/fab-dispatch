from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_meta_lists_algorithms_and_presets():
    body = client.get("/api/meta").json()
    assert set(body["algorithms"]) == {"greedy", "hungarian", "regret"}
    assert "litho_crunch" in body["presets"]


def test_generate_then_allocate_roundtrip():
    sc = client.post("/api/scenario", json={"seed": 1, "n_engineers": 8, "n_jobs": 20}).json()
    assert len(sc["engineers"]) == 8 and len(sc["jobs"]) == 20
    res = client.post("/api/allocate", json={"scenario": sc}).json()
    assert [r["algorithm"] for r in res] == ["greedy", "hungarian", "regret"]
    for r in res:
        assert r["metrics"]["assigned"] + len(r["unassigned"]) == 20


def test_rejects_bad_input():
    assert client.post("/api/scenario", json={"preset": "nope"}).status_code == 422
    sc = client.post("/api/scenario", json={"n_jobs": 3}).json()
    assert client.post("/api/allocate", json={"scenario": sc, "algorithms": ["magic"]}).status_code == 422
    sc["jobs"][0]["latest"] = sc["jobs"][0]["earliest"] - 1
    assert client.post("/api/allocate", json={"scenario": sc}).status_code == 422
