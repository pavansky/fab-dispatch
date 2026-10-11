"""Assistant feedback: recorded, deduplicated, validated, and exported as evaluation cases."""

import inspect
import json

from fastapi.testclient import TestClient

from app.assistant.agent import INTENTS
from app.main import app
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("viewer"))


def test_feedback_is_recorded_and_reported_to_dispatchers_only():
    fb = {"question": "Why is J006 assigned this way?", "intent": "job", "helpful": True, "citations": ["floor-plan"]}
    assert client.post("/api/assistant/feedback", json=fb).status_code == 204
    other = {**fb, "question": "What is E03 doing?", "helpful": False, "comment": "too long"}
    assert client.post("/api/assistant/feedback", json=other).status_code == 204
    assert client.get("/api/assistant/stats").status_code == 403  # viewers can rate, not read the stats
    dispatcher = TestClient(app, headers=auth_headers("dispatcher"))
    stats = dispatcher.get("/api/assistant/stats", params={"days": 7}).json()
    job = next(r for r in stats["by_intent"] if r["intent"] == "job")
    assert job["total"] >= 2 and 0 < job["helpful_rate"] < 1
    assert stats["total"] >= 2 and stats["days"] == 7


def test_feedback_on_the_same_question_updates_instead_of_piling_up():
    from app.deps import get_store

    q = "How is workload spread measured, really?"
    fb = {"question": q, "intent": "docs", "helpful": False, "comment": "wrong article", "citations": ["metrics"]}
    assert client.post("/api/assistant/feedback", json=fb).status_code == 204
    assert client.post("/api/assistant/feedback", json={**fb, "helpful": True, "comment": ""}).status_code == 204
    rows = [r for r in get_store().recent_feedback(days=1) if r["question"] == q]
    assert len(rows) == 1 and rows[0]["helpful"] is True and rows[0]["comment"] == ""
    assert "user_id" not in rows[0]


def test_feedback_intent_and_provider_must_be_the_servers_own_values():
    fb = {"question": "q", "intent": "docs", "helpful": True}
    assert (
        client.post("/api/assistant/feedback", json={**fb, "intent": "<img src=x onerror=alert(1)>"}).status_code == 422
    )
    assert client.post("/api/assistant/feedback", json={**fb, "intent": "jobs"}).status_code == 422
    assert client.post("/api/assistant/feedback", json={**fb, "provider": "<script>"}).status_code == 422
    assert client.post("/api/assistant/feedback", json={**fb, "citations": ["../etc"]}).status_code == 422
    assert (
        client.post("/api/assistant/feedback", json={**fb, "provider": "anthropic:claude-haiku-5-5"}).status_code == 204
    )
    for intent in sorted(INTENTS):
        assert (
            client.post("/api/assistant/feedback", json={**fb, "question": f"q {intent}", "intent": intent}).status_code
            == 204
        )


def test_feedback_rate_limit_is_ten_per_minute():
    from app.routes.help import assistant_feedback

    deps = inspect.signature(assistant_feedback).parameters["_rl"].default.dependency
    limit = inspect.getclosurevars(deps).nonlocals
    assert limit["name"] == "feedback" and limit["per_min"] == 10 and limit["burst"] <= 10, limit


def test_feedback_needs_sign_in_and_is_bounded():
    fb = {"question": "q", "intent": "docs", "helpful": True}
    assert TestClient(app).post("/api/assistant/feedback", json=fb).status_code == 401
    assert client.post("/api/assistant/feedback", json={**fb, "comment": "x" * 501}).status_code == 422
    assert client.post("/api/assistant/feedback", json={**fb, "citations": ["a"] * 11}).status_code == 422


def test_thumbs_down_with_comments_export_as_candidate_eval_cases(tmp_path):
    from scripts.feedback_to_eval import candidates, main

    q = "what does the purple ring around a job mean?"
    fb = {
        "question": q,
        "intent": "unknown",
        "helpful": False,
        "comment": "it's the coverage change ring",
        "citations": [],
    }
    assert client.post("/api/assistant/feedback", json=fb).status_code == 204
    assert (
        client.post("/api/assistant/feedback", json={**fb, "question": "silent downvote", "comment": ""}).status_code
        == 204
    )
    out = tmp_path / "candidates.json"
    assert main(["--days", "1", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert set(data) == {"_about", "docs", "refuse"}
    case = next(c for c in data["docs"] if c["q"] == q)
    assert case["cite"] == [] and case["_intent"] == "unknown" and "coverage change ring" in case["_comment"]
    assert case["_votes"] == 1 and not any(c["q"] == "silent downvote" for c in data["docs"])
    assert "user_id" not in json.dumps(data)
    # Grouping and ordering, without a database.
    rows = [
        {"question": "a", "intent": "docs", "helpful": False, "comment": "x", "citations": ["faq"]},
        {"question": "a", "intent": "docs", "helpful": False, "comment": "y", "citations": ["metrics"]},
        {"question": "b", "intent": "docs", "helpful": False, "comment": "z", "citations": []},
        {"question": "c", "intent": "docs", "helpful": True, "comment": "fine", "citations": []},
    ]
    docs = candidates(rows)["docs"]
    assert (
        [c["q"] for c in docs] == ["a", "b"] and docs[0]["_was_cited"] == ["faq", "metrics"] and docs[0]["_votes"] == 2
    )
