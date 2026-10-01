"""Help center content and the assistant.

Help articles are public (they're product documentation, useful on the sign-in screen too)
and cacheable. The assistant needs a signed-in user, because it reads the user's fab and
plans the shift they send.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..assistant import Answer, AskRequest, get_assistant
from ..assistant.index import get_index
from ..assistant.llm import rewrite
from ..auth import User, require
from ..config import get_settings
from ..deps import rate_limit
from ..help import get_article, table_of_contents
from ..http import etag_json
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api", tags=["help"])


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
    answer = get_assistant().ask(req.question, ctx)
    return rewrite(req.question, answer, get_settings())
