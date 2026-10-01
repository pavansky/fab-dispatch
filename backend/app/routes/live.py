"""Live shifts: create, drive the clock, report events, and stream changes (SSE)."""
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
from ..config import get_settings
from ..deps import get_store, rate_limit
from ..http import etag_json
from ..models import Job, Scenario, Weights
from ..store import NotFound, VersionConflict

router = APIRouter(prefix="/api/shifts", tags=["live"])


class CreateShift(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithm: str = "alns"


class Advance(BaseModel):
    minutes: float = Field(30, gt=0, le=720)


class ReportJob(BaseModel):
    job: Job


def _view(state: live.LiveState, version: int) -> dict:
    return {"version": version, "state": state.model_dump(mode="json"),
            "status": live.job_status(state), "progress": live.progress(state)}


def _load(shift_id: str) -> tuple[live.LiveState, int]:
    try:
        raw, version = get_store().get_shift(shift_id)
    except NotFound:
        raise HTTPException(404, f"shift {shift_id} not found") from None
    return live.LiveState.model_validate(raw), version


def _mutate(shift_id: str, action: Callable[[live.LiveState], list[dict]], if_match: str | None) -> dict:
    """Read, apply, write with an optimistic version check. Retry on a lost race unless the
    caller pinned a version with If-Match, in which case report the conflict (409)."""
    store = get_store()
    for _ in range(3):
        state, version = _load(shift_id)
        if if_match is not None and if_match.strip('"') != str(version):
            raise HTTPException(409, f"shift changed (now version {version}); reload and retry")
        try:
            events = action(state)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        try:
            new_version = store.save_shift(shift_id, state.model_dump(mode="json"), version)
        except VersionConflict:
            if if_match is not None:
                raise HTTPException(409, "shift changed concurrently; reload and retry") from None
            continue
        if events:
            store.append_events(shift_id, [{**e, "version": new_version} for e in events])
        return {**_view(state, new_version), "events": events}
    raise HTTPException(409, "shift is busy; retry")


@router.post("", dependencies=[Depends(rate_limit("shift", 30, 10))])
def create_shift(req: CreateShift) -> dict:
    if req.algorithm not in ALGORITHMS:
        raise HTTPException(422, f"unknown algorithm {req.algorithm!r}")
    state, events = live.start(req.scenario, req.weights, req.algorithm)
    store = get_store()
    store.create_shift(state.id, state.model_dump(mode="json"))
    store.append_events(state.id, [{**e, "version": 1} for e in events])
    return {**_view(state, 1), "events": events}


@router.get("")
def list_shifts(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return get_store().list_shifts(limit)


@router.get("/{shift_id}")
def get_shift(shift_id: str, request: Request):
    state, version = _load(shift_id)
    return etag_json(request, _view(state, version))


@router.post("/{shift_id}/advance", dependencies=[Depends(rate_limit("live", 240, 30))])
def advance(shift_id: str, req: Advance, if_match: str | None = Header(None)) -> dict:
    return _mutate(shift_id, lambda s: live.advance(s, req.minutes), if_match)


@router.post("/{shift_id}/jobs", dependencies=[Depends(rate_limit("live", 240, 30))])
def report_job(shift_id: str, req: ReportJob, if_match: str | None = Header(None)) -> dict:
    return _mutate(shift_id, lambda s: live.report_job(s, req.job), if_match)


@router.post("/{shift_id}/engineers/{engineer_id}/off", dependencies=[Depends(rate_limit("live", 240, 30))])
def engineer_off(shift_id: str, engineer_id: str, if_match: str | None = Header(None)) -> dict:
    return _mutate(shift_id, lambda s: live.engineer_off(s, engineer_id), if_match)


@router.get("/{shift_id}/events")
def events(shift_id: str, after: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500)) -> list[dict]:
    _load(shift_id)
    return get_store().events_after(shift_id, after, limit)


@router.get("/{shift_id}/stream")
async def stream(shift_id: str, request: Request, last_event_id: str | None = Header(None)):
    """Server-Sent Events. The stream tails the shift's event log by id, so it works with
    many server instances and resumes on reconnect (EventSource sends Last-Event-ID).
    Each response closes after ``sse_window_s``, which stays inside serverless limits;
    the browser reconnects on its own."""
    await to_thread.run_sync(_load, shift_id)
    store, settings = get_store(), get_settings()
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else int(request.query_params.get("after", 0))

    async def gen():
        nonlocal cursor
        yield "retry: 1500\n\n"
        deadline = time.monotonic() + settings.sse_window_s
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            batch = await to_thread.run_sync(store.events_after, shift_id, cursor, 100)
            for e in batch:
                cursor = e["id"]
                yield f"id: {e['id']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n"
            if time.monotonic() - last_beat > 10:
                yield ": keep-alive\n\n"
                last_beat = time.monotonic()
            await asyncio.sleep(0.5 if not batch else 0.05)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
