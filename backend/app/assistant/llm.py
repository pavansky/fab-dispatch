"""Optional: let a language model rewrite a grounded answer in plainer words.

Off by default (``FAB_ASSISTANT_LLM=none``): the assistant is fully local and needs no key.
When enabled, the model only sees the question and the **grounded answer** (built from the
help articles and the plans), and is told to use nothing else. Citations and actions are
kept from the grounded answer, never generated. Any failure (timeout, error, empty reply)
returns the grounded answer unchanged, so the model can improve wording but can't break
or invent anything the user relies on.

Providers use the standard library (``urllib``), so enabling one adds no dependency:

* ``anthropic``: Claude via the Messages API (``ANTHROPIC_API_KEY``).
* ``ollama``: any model on a local Ollama server, still with no cloud and no key.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable

from ..config import Settings
from .agent import Answer

log = logging.getLogger("fab")

DEFAULT_MODELS = {"anthropic": "claude-haiku-4-5-20251001", "ollama": "llama3.2"}

SYSTEM = (
    "You rewrite answers for the help assistant of Fab Dispatch, a tool that assigns maintenance "
    "engineers to tool-downs in a semiconductor fab. You get a user's question and a DRAFT answer that "
    "is correct and grounded in the app's data. Rewrite the draft to answer the question directly and "
    "clearly, in at most 150 words, keeping Markdown, numbers, ids (like J006, E03) and tables exactly. "
    "Use ONLY facts in the draft. Never add facts, advice or numbers that aren't in it. If the draft says "
    "it doesn't know, say the same."
)

Transport = Callable[[str, dict, dict, float], dict]


def _post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _prompt(question: str, draft: str) -> str:
    return f"Question: {question}\n\nDRAFT answer:\n{draft}"


def rewrite(question: str, answer: Answer, settings: Settings, transport: Transport = _post) -> Answer:
    provider = settings.assistant_llm
    # Refusals and no-shift replies are already as clear as they can be: don't spend a call.
    if provider == "none" or answer.intent in {"unknown", "greeting"} or not answer.grounded:
        return answer
    model = settings.assistant_model or DEFAULT_MODELS[provider]
    try:
        if provider == "anthropic":
            if not settings.anthropic_api_key:
                return answer
            out = transport(
                "https://api.anthropic.com/v1/messages",
                {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
                {
                    "model": model,
                    "max_tokens": 600,
                    "system": SYSTEM,
                    "messages": [{"role": "user", "content": _prompt(question, answer.answer)}],
                },
                settings.assistant_llm_timeout_s,
            )
            text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
        else:
            out = transport(
                f"{settings.ollama_url.rstrip('/')}/api/chat",
                {},
                {
                    "model": model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": _prompt(question, answer.answer)},
                    ],
                },
                settings.assistant_llm_timeout_s,
            )
            text = out.get("message", {}).get("content", "")
    except Exception as e:  # any provider failure falls back to the grounded answer
        log.warning("assistant llm (%s) failed, using grounded answer: %s", provider, e)
        return answer
    text = text.strip()
    if not text:
        return answer
    return answer.model_copy(update={"answer": text, "provider": f"{provider}:{model}"})
