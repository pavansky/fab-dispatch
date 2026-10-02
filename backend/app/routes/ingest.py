"""Machine-to-machine ingestion: equipment and MES systems report tool-downs directly.

In a fab, a tool going down is detected by the tool or the MES, not typed by a dispatcher. This
endpoint is that integration point:

* **Authentication** by a per-fab token (``Authorization: Bearer …``). The server stores only
  its SHA-256 (``FAB_INGEST_TOKENS``) and compares in constant time. A token can only post to
  its own fab, and only report work: it can't read plans or change anything else.
* **At-least-once delivery** is the norm for integrations, so ``Idempotency-Key`` is required:
  a retried message returns the first response instead of reporting the fault twice.
* **Routing**: the tool-down joins the fab's active live shift (or the one named), and is
  re-planned there exactly as if a dispatcher had reported it. Viewers see it live.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .. import live
from ..auth import User
from ..config import get_settings
from ..deps import get_store, rate_limit
from ..fabs import UnknownFab, get_profile
from ..models import Job
from .live import _mutate

router = APIRouter(prefix="/api/ingest", tags=["integration"])


class ToolDown(BaseModel):
    fab_id: str
    job: Job
    shift_id: str | None = None


def _integration(fab_id: str, authorization: str | None) -> User:
    expected = get_settings().ingest_tokens.get(fab_id)
    token = (authorization or "").removeprefix("Bearer ").strip()
    given = hashlib.sha256(token.encode()).hexdigest()
    if not expected or not token or not hmac.compare_digest(given, expected.lower()):
        raise HTTPException(401, "invalid ingestion token for this fab")
    return User(
        id=f"ingest:{fab_id}", email=f"integration ({fab_id})", role="dispatcher", fabs=[fab_id], provider="integration"
    )


@router.post("/tool-downs", status_code=202)
def tool_down(
    req: ToolDown,
    authorization: str | None = Header(None),
    idempotency_key: str = Header(..., description="unique per message; retries reuse it"),
    _rl: None = Depends(rate_limit("ingest", 600, 60)),
) -> dict:
    user = _integration(req.fab_id, authorization)
    try:
        profile = get_profile(req.fab_id)
    except UnknownFab:
        raise HTTPException(404, f"fab {req.fab_id} not found") from None
    if req.job.skill not in {f.id for f in profile.families}:
        raise HTTPException(422, f"{req.fab_id} has no {req.job.skill!r} tools")
    shift_id = req.shift_id or next(
        (s["id"] for s in get_store(req.fab_id).list_shifts(req.fab_id, 20) if not s["ended"]), None
    )
    if shift_id is None:
        raise HTTPException(409, f"{req.fab_id} has no live shift to receive the tool-down")
    job = req.job.model_copy(update={"kind": "down"})
    out = _mutate(shift_id, user, lambda s: live.report_job(s, job, user.email), None, idempotency_key)
    return {
        "shift_id": shift_id,
        "job_id": job.id,
        "status": out["status"].get(job.id, "unknown"),
        "version": out["version"],
        "idempotent_replay": out.get("idempotent_replay", False),
    }
