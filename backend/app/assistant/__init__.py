"""The in-app assistant: grounded answers about the app and the shift on screen."""

from __future__ import annotations

from functools import lru_cache

from .agent import Action, Answer, AskContext, AskRequest, Assistant, Citation

__all__ = ["Action", "Answer", "AskContext", "AskRequest", "Assistant", "Citation", "get_assistant"]


@lru_cache
def get_assistant() -> Assistant:
    from ..deps import get_planning
    from ..fabs import get_profile
    from .index import get_index

    planning = get_planning()
    return Assistant(get_index(), lambda sc, w, a: planning.plan(sc, w, a).result, get_profile)
