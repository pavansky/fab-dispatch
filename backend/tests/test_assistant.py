"""The assistant: grounded answers, honest refusals, and a measured retrieval quality bar."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.assistant import Answer, AskContext
from app.assistant.agent import classify
from app.assistant.index import get_index
from app.assistant.llm import rewrite
from app.config import Settings
from app.main import app
from tests.conftest import auth_headers

client = TestClient(app, headers=auth_headers("viewer"))
EVAL = json.loads((Path(__file__).parent / "eval" / "assistant_eval.json").read_text())
MIN_RETRIEVAL_ACCURACY = 0.9


@pytest.fixture(scope="module")
def shift():
    sc = client.post("/api/scenario", json={"preset": "litho_crunch", "seed": 7, "n_engineers": 6, "n_jobs": 18}).json()
    plans = {a: client.post("/api/plan", json={"scenario": sc, "algorithm": a}).json() for a in ["greedy", "pyvrp"]}
    return sc, plans


def ask(question, **context):
    r = client.post("/api/assistant/ask", json={"question": question, "context": context})
    assert r.status_code == 200, r.text
    return r.json()


# ----------------------------------------------------------------------------- quality bar
def test_retrieval_cites_the_right_article_for_real_questions():
    index = get_index()
    misses = []
    for case in EVAL["docs"]:
        expected = case["cite"] if isinstance(case["cite"], list) else [case["cite"]]
        top = index.search(case["q"], k=1)[0]
        if top.slug not in expected or top.score < 0.5:
            misses.append((case["q"], expected, top.slug, top.score))
    accuracy = 1 - len(misses) / len(EVAL["docs"])
    assert accuracy >= MIN_RETRIEVAL_ACCURACY, f"accuracy {accuracy:.0%}, misses: {misses}"


@pytest.mark.parametrize("question", EVAL["refuse"])
def test_out_of_scope_questions_get_an_honest_i_dont_know(question):
    a = ask(question)
    assert a["intent"] == "unknown"
    assert a["answer"].startswith("I don't know")


# ----------------------------------------------------------------------------- understanding
@pytest.mark.parametrize(
    "question, intent",
    [
        ("Why is J006 unassigned?", "job"),
        ("what is e03 doing", "engineer"),
        ("Why is PyVRP recommended?", "recommendation"),
        ("Which strategy is best?", "recommendation"),
        ("Compare greedy and hungarian", "compare"),
        ("greedy vs alns", "compare"),
        ("Which jobs are unassigned?", "unassigned"),
        ("How do I report a tool-down?", "docs"),
        ("hello", "greeting"),
    ],
)
def test_questions_are_routed_to_the_right_tool(question, intent):
    assert classify(question, AskContext())[0] == intent


def test_this_job_resolves_to_the_selection():
    ctx = AskContext(selection={"type": "job", "id": "J004"})
    assert classify("why is this job unassigned?", ctx) == ("job", {"jobs": ["J004"], "engineers": [], "algos": []})


# ----------------------------------------------------------------------------- grounded answers
def test_job_answer_matches_the_plans_exactly(shift):
    sc, plans = shift
    a = ask("Why is J006 assigned this way?", scenario=sc)
    assert a["intent"] == "job"
    assert a["answer"].startswith("**J006**")
    greedy = next((u for u in plans["greedy"]["unassigned"] if u["job_id"] == "J006"), None)
    pyvrp = next((x for x in plans["pyvrp"]["assignments"] if x["job_id"] == "J006"), None)
    assert greedy and greedy["reason"] in a["answer"]  # the same reason the UI shows
    assert pyvrp and f"**PyVRP:** {pyvrp['tech_id']}" in a["answer"]
    assert {"label": "Open J006 on the floor plan", "kind": "job", "target": "J006"} in a["actions"]
    assert a["citations"][0]["slug"] == "floor-plan"


def test_job_answer_can_focus_on_one_strategy(shift):
    sc, _ = shift
    a = ask("why did greedy leave J006?", scenario=sc)
    assert "**Greedy:**" in a["answer"] and "**PyVRP:**" not in a["answer"]


def test_unknown_job_is_said_plainly_not_guessed(shift):
    sc, _ = shift
    a = ask("why is J999 unassigned?", scenario=sc)
    assert "no **J999**" in a["answer"] and "J001 to J018" in a["answer"]


def test_job_question_without_a_shift_asks_for_one():
    a = ask("why is J006 unassigned?")
    assert "need a shift" in a["answer"]


def test_engineer_answer_lists_their_route_in_order(shift):
    sc, plans = shift
    route = next(r for r in plans["pyvrp"]["routes"] if len(r["stops"]) > 1)
    a = ask(f"What is {route['tech_id']} doing?", scenario=sc, active="pyvrp")
    assert a["intent"] == "engineer"
    positions = [a["answer"].index(f"**{s['job_id']}**") for s in route["stops"]]
    assert positions == sorted(positions)
    assert {"label": f"Open {route['tech_id']}", "kind": "engineer", "target": route["tech_id"]} in a["actions"]


def test_recommendation_explains_what_the_screen_recommends(shift):
    sc, _ = shift
    reco = {"algorithm": "pyvrp", "goal": "value", "goal_label": "Best value", "why": "Cheapest plan by a real margin."}
    a = ask("why is pyvrp recommended?", scenario=sc, recommendation=reco)
    assert a["answer"].startswith("**PyVRP** is recommended")
    assert "Cheapest plan by a real margin." in a["answer"]
    assert "| **PyVRP** |" in a["answer"]  # metric table, recommended row highlighted
    assert a["citations"][0]["slug"] == "recommendation"


def test_compare_combines_docs_and_this_shifts_numbers(shift):
    sc, plans = shift
    a = ask("compare greedy and pyvrp", scenario=sc)
    assert "**Greedy.**" in a["answer"] and "**PyVRP.**" in a["answer"]
    assert "On this shift" in a["answer"]
    assert str(plans["greedy"]["metrics"]["objective"]).rstrip("0").rstrip(".") in a["answer"]


def test_unassigned_lists_every_unserved_job_with_reasons(shift):
    sc, plans = shift
    a = ask("which jobs are unassigned?", scenario=sc, active="greedy")
    for u in plans["greedy"]["unassigned"]:
        assert f"**{u['job_id']}**" in a["answer"] and u["reason"] in a["answer"]


def test_docs_answer_quotes_the_article_and_links_to_it():
    a = ask("How do I report a tool-down during a live shift?")
    assert a["intent"] == "docs"
    assert "Tap floor to report a bottleneck down" in a["answer"]
    assert a["citations"][0] == {
        "slug": "live-dispatch",
        "title": "Live dispatch",
        "heading": "Report a bottleneck down",
        "anchor": "report-a-bottleneck-down",
    }
    assert a["actions"][0]["kind"] == "help"


def test_greeting_offers_context_aware_suggestions():
    a = ask("hi", selection={"type": "job", "id": "J004"})
    assert a["suggestions"][0] == "Why is J004 assigned this way?"


# ----------------------------------------------------------------------------- access
def test_assistant_needs_sign_in():
    assert TestClient(app).post("/api/assistant/ask", json={"question": "hi"}).status_code == 401


def test_assistant_rejects_empty_and_oversized_questions():
    assert client.post("/api/assistant/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/assistant/ask", json={"question": "x" * 501}).status_code == 422


def test_assistant_respects_fab_scoping(shift):
    import jwt

    from app.auth import issue_demo_token
    from app.config import get_settings

    s = get_settings()
    claims = jwt.decode(issue_demo_token("viewer", s), s.auth_secret, algorithms=["HS256"], audience="fab-dispatch")
    claims["fabs"] = ["fab2-200mm-analog"]
    fab2_only = TestClient(app, headers={"Authorization": f"Bearer {jwt.encode(claims, s.auth_secret)}"})
    sc, _ = shift  # a fab 1 shift
    r = fab2_only.post("/api/assistant/ask", json={"question": "why is J006 unassigned?", "context": {"scenario": sc}})
    assert r.status_code == 404


# ----------------------------------------------------------------------------- optional LLM
GROUNDED = Answer(answer="**J006**: unassigned by Greedy.", intent="job", citations=[], actions=[])


def test_llm_is_off_by_default_and_never_called():
    def boom(*_):
        raise AssertionError("no call expected")

    assert rewrite("q", GROUNDED, Settings(), transport=boom) == GROUNDED


def test_llm_rewrites_only_the_text_and_records_the_provider():
    seen = {}

    def fake(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return {"content": [{"type": "text", "text": "J006 isn't served by Greedy."}]}

    s = Settings(assistant_llm="anthropic", anthropic_api_key="test-key")
    out = rewrite("why J006?", GROUNDED, s, transport=fake)
    assert out.answer == "J006 isn't served by Greedy."
    assert out.provider == "anthropic:claude-haiku-4-5-20251001"
    assert out.citations == GROUNDED.citations and out.intent == "job"
    assert seen["url"].endswith("/v1/messages") and seen["headers"]["x-api-key"] == "test-key"
    assert "Use ONLY facts in the draft" in seen["body"]["system"]
    assert GROUNDED.answer in seen["body"]["messages"][0]["content"]


def test_llm_via_local_ollama():
    s = Settings(assistant_llm="ollama", assistant_model="llama3.2")
    out = rewrite("q", GROUNDED, s, transport=lambda *_: {"message": {"content": "Plainer."}})
    assert out.answer == "Plainer." and out.provider == "ollama:llama3.2"


@pytest.mark.parametrize("failure", [TimeoutError("slow"), ValueError("bad json"), {"content": []}])
def test_llm_failure_falls_back_to_the_grounded_answer(failure):
    def transport(*_):
        if isinstance(failure, Exception):
            raise failure
        return failure

    s = Settings(assistant_llm="anthropic", anthropic_api_key="k")
    assert rewrite("q", GROUNDED, s, transport=transport) == GROUNDED


def test_llm_is_not_asked_to_reword_refusals_or_used_without_a_key():
    refusal = GROUNDED.model_copy(update={"intent": "unknown"})
    s = Settings(assistant_llm="anthropic", anthropic_api_key="k")
    assert rewrite("q", refusal, s, transport=lambda *_: 1 / 0) == refusal
    assert rewrite("q", GROUNDED, Settings(assistant_llm="anthropic"), transport=lambda *_: 1 / 0) == GROUNDED
