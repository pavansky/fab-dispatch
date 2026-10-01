"""Live shifts: create, drive the clock, report events, and stream changes (SSE).

Production behaviours on every mutating call:

* **Roles**: viewers can watch; only dispatchers change a shift.
* **Fab scoping**: a shift is visible only to users with access to its fab.
* **Optimistic concurrency**: writes are version-checked; ``If-Match`` pins a version.
* **Idempotency**: an ``Idempotency-Key`` header makes a retried request return the
  first response instead of applying the change twice.
* **Clock lease**: only one dispatcher drives the clock at a time.
* **Audit**: every event records the acting user.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from .. import live
from ..algorithms import ALGORITHMS
from ..auth import User, require
from ..config import get_settings
from ..deps import get_store, rate_limit
from ..http import etag_json
from ..models import Job, Scenario, Weights
from ..store import NotFound, VersionConflict
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api/shifts", tags=["live"])
SSE_POLL_MIN_S, SSE_POLL_MAX_S = 0.25, 2.0


class CreateShift(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithm: str = "alns"


class Advance(BaseModel):
    minutes: float = Field(30, gt=0, le=24 * 60)


class ReportJob(BaseModel):
    job: Job


def _view(state: live.LiveState, version: int, viewers: list[str] | None = None) -> dict:
    return {
        "version": version,
        "state": state.model_dump(mode="json"),
        "status": live.job_status(state),
        "progress": live.progress(state),
        "viewers": viewers or [],
        "clock_driver": state.driver if state.driver_until > time.time() else None,
    }


def _load(shift_id: str, user: User) -> tuple[live.LiveState, int]:
    # Tenant scope is enforced twice: in the SQL (a shift in another fab is never read) and
    # here, so a store that ignored the scope still couldn't leak one.
    try:
        raw, version = get_store().get_shift(shift_id, fabs=user.fabs)
    except NotFound:
        raise HTTPException(404, f"shift {shift_id} not found") from None
    state = live.LiveState.model_validate(raw)
    if not user.can_access(state.fab_id):
        raise HTTPException(404, f"shift {shift_id} not found")
    return state, version


def _mutate(
    shift_id: str,
    user: User,
    action: Callable[[live.LiveState], list[dict]],
    if_match: str | None,
    idem_key: str | None,
) -> dict:
    """Read, apply, write with an optimistic version check. Retry on a lost race unless the
    caller pinned a version with If-Match (then report 409). Idempotency-Key replays."""
    store = get_store()
    scoped_key = f"{user.id}:{shift_id}:{idem_key}" if idem_key else None
    if scoped_key and (previous := store.get_idempotent(scoped_key)) is not None:
        return {**previous, "idempotent_replay": True}
    for _ in range(3):
        state, version = _load(shift_id, user)
        if if_match is not None and if_match.strip('"') != str(version):
            raise HTTPException(409, f"shift changed (now version {version}); reload and retry")
        try:
            events = action(state)
        except live.ClockBusy as e:
            raise HTTPException(409, f"{e} is driving the clock right now") from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        try:
            new_version = store.save_shift(
                shift_id, state.model_dump(mode="json"), version, assignments=live.assignment_rows(state)
            )
        except VersionConflict:
            if if_match is not None:
                raise HTTPException(409, "shift changed concurrently; reload and retry") from None
            continue
        if events:
            store.append_events(shift_id, [{**e, "version": new_version} for e in events])
        out = {**_view(state, new_version, store.presence(shift_id)), "events": events}
        if scoped_key:
            store.put_idempotent(scoped_key, out)
        return out
    raise HTTPException(409, "shift is busy; retry")


@router.post("")
def create_shift(
    req: CreateShift, user: User = Depends(require("dispatcher")), _rl: None = Depends(rate_limit("shift", 30, 10))
) -> dict:
    if req.algorithm not in ALGORITHMS:
        raise HTTPException(422, f"unknown algorithm {req.algorithm!r}")
    check_scenario(user, req.scenario)
    state, events = live.start(req.scenario, req.weights, req.algorithm, user.email)
    store = get_store()
    store.create_shift(
        state.id, state.model_dump(mode="json"), state.fab_id, user.email, assignments=live.assignment_rows(state)
    )
    store.append_events(state.id, [{**e, "version": 1} for e in events])
    return {**_view(state, 1), "events": events}


@router.get("")
def list_shifts(
    fab_id: str = Query(...), limit: int = Query(20, ge=1, le=100), user: User = Depends(require("viewer"))
) -> list[dict]:
    fab_for(user, fab_id)
    return get_store().list_shifts(fab_id, limit)


@router.get("/{shift_id}")
def get_shift(shift_id: str, request: Request, user: User = Depends(require("viewer"))):
    state, version = _load(shift_id, user)
    return etag_json(request, _view(state, version, get_store().presence(shift_id)))


@router.post("/{shift_id}/advance")
def advance(
    shift_id: str,
    req: Advance,
    user: User = Depends(require("dispatcher")),
    if_match: str | None = Header(None),
    idempotency_key: str | None = Header(None),
    _rl: None = Depends(rate_limit("live", 240, 30)),
) -> dict:
    return _mutate(shift_id, user, lambda s: live.advance(s, req.minutes, user.email), if_match, idempotency_key)


@router.post("/{shift_id}/release")
def release(shift_id: str, user: User = Depends(require("dispatcher"))) -> dict:
    """Give up the clock (on pause), so another dispatcher can drive without waiting."""
    return _mutate(shift_id, user, lambda s: live.release_clock(s, user.email), None, None)


@router.post("/{shift_id}/jobs")
def report_job(
    shift_id: str,
    req: ReportJob,
    user: User = Depends(require("dispatcher")),
    if_match: str | None = Header(None),
    idempotency_key: str | None = Header(None),
    _rl: None = Depends(rate_limit("live", 240, 30)),
) -> dict:
    return _mutate(shift_id, user, lambda s: live.report_job(s, req.job, user.email), if_match, idempotency_key)


@router.post("/{shift_id}/engineers/{engineer_id}/off")
def engineer_off(
    shift_id: str,
    engineer_id: str,
    user: User = Depends(require("dispatcher")),
    if_match: str | None = Header(None),
    idempotency_key: str | None = Header(None),
    _rl: None = Depends(rate_limit("live", 240, 30)),
) -> dict:
    return _mutate(shift_id, user, lambda s: live.engineer_off(s, engineer_id, user.email), if_match, idempotency_key)


@router.get("/{shift_id}/assignments")
def shift_assignments(shift_id: str, user: User = Depends(require("viewer"))) -> list[dict]:
    """The shift's current assignments from the read model: one row per known job."""
    _load(shift_id, user)
    return get_store().shift_assignments(shift_id)


@router.get("/{shift_id}/events")
def events(
    shift_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(require("viewer")),
) -> list[dict]:
    _load(shift_id, user)
    return get_store().events_after(shift_id, after, limit)


@router.get("/{shift_id}/stream")
async def stream(
    shift_id: str, request: Request, last_event_id: str | None = Header(None), user: User = Depends(require("viewer"))
):
    """Server-Sent Events. The stream tails the shift's event log by id, so it works with
    many server instances and resumes on reconnect (EventSource sends Last-Event-ID).
    Each response closes after ``sse_window_s``, which stays inside serverless limits;
    the browser reconnects on its own. Open streams double as presence heartbeats."""
    await to_thread.run_sync(_load, shift_id, user)
    store, settings = get_store(), get_settings()
    cursor = (
        int(last_event_id) if last_event_id and last_event_id.isdigit() else int(request.query_params.get("after", 0))
    )

    async def gen():
        nonlocal cursor
        yield "retry: 1500\n\n"
        deadline = time.monotonic() + settings.sse_window_s
        last_beat = 0.0
        idle = SSE_POLL_MIN_S
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            if time.monotonic() - last_beat > 10:
                await to_thread.run_sync(store.touch_presence, shift_id, user.id, user.email)
                yield ": keep-alive\n\n"
                last_beat = time.monotonic()
            batch = await to_thread.run_sync(store.events_after, shift_id, cursor, 100)
            for e in batch:
                cursor = e["id"]
                yield f"id: {e['id']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n"
            # Back off while the shift is quiet; snap back the moment something happens. A busy
            # shift is polled every 0.25 s, an idle one every 2 s: ~8x fewer queries per viewer.
            idle = SSE_POLL_MIN_S if batch else min(idle * 1.5, SSE_POLL_MAX_S)
            await asyncio.sleep(0.05 if len(batch) == 100 else idle)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
