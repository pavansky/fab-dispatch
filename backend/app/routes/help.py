"""Help center content and the assistant.

Help articles are public (they're product documentation, useful on the sign-in screen too)
and cacheable. The assistant needs a signed-in user, because it reads the user's fab and
plans the shift they send.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..assistant import Answer, AskRequest, get_assistant
from ..assistant.index import get_index
from ..assistant.llm import rewrite
from ..auth import User, require
from ..config import get_settings
from ..deps import get_store, rate_limit
from ..help import get_article, table_of_contents
from ..http import etag_json
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api", tags=["help"])
log = logging.getLogger("fab")


@router.get("/help")
def help_index(request: Request):
    return etag_json(request, {"sections": table_of_contents()})


@router.get("/help/search")
def help_search(q: str = Query(..., min_length=1, max_length=200), _rl: None = Depends(rate_limit("help", 120, 30))):
    seen, out = set(), []
    for h in get_index().search(q, k=12):
        if h.slug in seen or h.score < 0.35:
            continue
        seen.add(h.slug)
        snippet = h.text.replace("\n", " ")
        out.append({**h.citation(), "snippet": snippet[:180] + ("…" if len(snippet) > 180 else ""), "score": h.score})
    return {"query": q, "results": out[:6]}


@router.get("/help/{slug}")
def help_article(slug: str, request: Request):
    article = get_article(slug)
    if not article:
        raise HTTPException(404, f"no help article {slug!r}")
    body = article.model_dump(include={"slug", "title", "summary", "section", "body"})
    body["sections"] = [{"heading": s.heading, "anchor": s.anchor} for s in article.sections if s.anchor]
    return etag_json(request, body)


class Feedback(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    intent: str = Field(max_length=40)
    helpful: bool
    comment: str = Field("", max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=10, description="cited article slugs")
    provider: str = Field("local", max_length=80)


@router.post("/assistant/feedback", status_code=204)
def assistant_feedback(
    fb: Feedback, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("feedback", 30, 10))
) -> None:
    """Thumbs up/down on an answer. Stored with the user id (not the email) for 180 days; it feeds
    the assistant's evaluation set, which is how answers get better."""
    get_store().add_feedback({**fb.model_dump(), "user_id": user.id})


@router.get("/assistant/stats")
def assistant_stats(days: int = Query(30, ge=1, le=180), _user: User = Depends(require("dispatcher"))) -> dict:
    """Answer quality in production: how often answers were marked helpful, by kind of question."""
    rows = get_store().feedback_stats(days)
    total = sum(r["total"] for r in rows)
    helpful = sum(r["helpful"] for r in rows)
    return {
        "days": days,
        "total": total,
        "helpful_rate": round(helpful / total, 3) if total else None,
        "by_intent": [{**r, "helpful_rate": round(r["helpful"] / r["total"], 3)} for r in rows],
    }


@router.post("/assistant/ask", response_model=Answer)
def ask(
    req: AskRequest,
    user: User = Depends(require("viewer")),
    _rl: None = Depends(rate_limit("assistant", 30, 10)),
) -> Answer:
    ctx = req.context
    if ctx.scenario is not None:
        check_scenario(user, ctx.scenario)  # same fab scoping and size limits as /plan
    elif ctx.fab_id:
        fab_for(user, ctx.fab_id)
    t0 = time.perf_counter()
    answer = rewrite(req.question, get_assistant().ask(req.question, ctx), get_settings())
    # One structured line per answer: what kind of question, where the answer came from, how fast.
    log.info(
        "assistant intent=%s citations=%s provider=%s ms=%.0f",
        answer.intent,
        ",".join(c.slug for c in answer.citations) or "-",
        answer.provider,
        (time.perf_counter() - t0) * 1000,
    )
    return answer
