"""Live shifts: create, drive the clock, report events, and stream changes (SSE).

Production behaviours on every mutating call:

* **Roles**: viewers can watch; only dispatchers change a shift.
* **Guests own their shifts**: an anonymous (guest) dispatcher may only advance, report on,
  call engineers off or release the shifts they started; named dispatchers share every shift
  in their fabs. Guests still see every shift.
* **Fab scoping**: a shift is visible only to users with access to its fab.
* **Optimistic concurrency**: writes are version-checked; ``If-Match`` pins a version
  (send back the ``ETag`` from ``GET /shifts/{id}``, or a quoted version).
* **Ended shifts are final**: every write to an ended shift is refused with 409, and an
  action that changes nothing (releasing a clock you don't hold) doesn't bump the version.
* **Idempotency**: an ``Idempotency-Key`` header makes a retried request return the
  first response instead of applying the change twice. The key is claimed in the same
  transaction as the write, so even two concurrent requests with one key apply once.
* **Clock lease**: only one dispatcher drives the clock at a time.
* **Audit**: every event records the acting user.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from .. import live
from ..algorithms import ALGORITHMS
from ..auth import STREAM_TICKET_TTL_S, User, issue_stream_ticket, require
from ..config import get_settings
from ..deps import get_store, rate_limit, store_for_shift
from ..http import etag_json, if_match_version
from ..models import Job, Scenario, Weights
from ..store import DuplicateRequest, NotFound, VersionConflict
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api/shifts", tags=["live"])
SSE_POLL_MIN_S, SSE_POLL_MAX_S = 0.25, 2.0
SSE_BUSY_POLL_MIN_S = 1.0  # the poll floor once this instance serves more than SSE_BUSY_STREAMS streams
SSE_BUSY_STREAMS = 32
SSE_MAX_STREAMS_PER_USER = 4  # open streams per user per instance; beyond it the stream answers 429


class OpenStreams:
    """How many SSE streams each user holds open on this instance. Every open stream polls the
    database, so a client that keeps opening streams (a tab loop, a script) is capped per user,
    and the polling floor rises for everyone once the instance is busy."""

    def __init__(self, per_user: int = SSE_MAX_STREAMS_PER_USER):
        self.per_user = per_user
        self._by_user: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, user_id: str) -> bool:
        with self._lock:
            if self._by_user.get(user_id, 0) >= self.per_user:
                return False
            self._by_user[user_id] = self._by_user.get(user_id, 0) + 1
            return True

    def release(self, user_id: str) -> None:
        with self._lock:
            left = self._by_user.get(user_id, 0) - 1
            if left > 0:
                self._by_user[user_id] = left
            else:
                self._by_user.pop(user_id, None)

    @property
    def total(self) -> int:
        with self._lock:
            return sum(self._by_user.values())

    def poll_floor(self) -> float:
        return SSE_BUSY_POLL_MIN_S if self.total > SSE_BUSY_STREAMS else SSE_POLL_MIN_S


open_streams = OpenStreams()


class CreateShift(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithm: str = "alns"


class Advance(BaseModel):
    minutes: float = Field(30, gt=0, le=24 * 60)


class ReportJob(BaseModel):
    job: Job


def _view(state: live.LiveState, version: int, viewers: list[str] | None = None) -> dict:
    """What clients see. Only jobs known so far are listed: a tool-down that hasn't been
    reported yet (its tool, symptom and future failure time) stays on the server, exactly as
    the planner never peeks at it. ``progress.total`` still counts every job."""
    shown = state.model_dump(mode="json")
    known = set(state.released)
    shown["scenario"]["jobs"] = [j for j in shown["scenario"]["jobs"] if j["id"] in known]
    return {
        "version": version,
        "state": shown,
        "status": live.job_status(state),
        "progress": live.progress(state),
        "viewers": viewers or [],
        "clock_driver": state.driver if state.driver_until > time.time() else None,
    }


def _load(shift_id: str, user: User) -> tuple[live.LiveState, int]:
    # Tenant scope is enforced twice: in the SQL (a shift in another fab is never read) and
    # here, so a store that ignored the scope still couldn't leak one.
    try:
        raw, version = store_for_shift(shift_id).get_shift(shift_id, fabs=user.fabs)
    except NotFound:
        raise HTTPException(404, f"shift {shift_id} not found") from None
    state = live.LiveState.model_validate(raw)
    if not user.can_access(state.fab_id):
        raise HTTPException(404, f"shift {shift_id} not found")
    return state, version


def _check_may_change(state: live.LiveState, user: User) -> None:
    """A guest (anonymous sign-in) changes only shifts it started: on a public demo every guest is
    a dispatcher by configuration, and shifts are per fab, so without this any guest could drive,
    report on or strip engineers from any other guest's shift. Named dispatchers share shifts."""
    if user.provider == "guest" and state.created_by != user.email:
        raise HTTPException(403, "Guests can only change live shifts they started; start your own shift")


def _mutate(
    shift_id: str,
    user: User,
    action: Callable[[live.LiveState], list[dict]],
    if_match: str | None,
    idem_key: str | None,
) -> dict:
    """Read, apply, write with an optimistic version check. Retry on a lost race unless the
    caller pinned a version with If-Match (then report 409).

    Idempotency-Key: the key is checked before every attempt (a concurrent request with the same
    key may have won the race we just lost) and claimed inside the write's transaction together
    with the shift, its read model and its events. Two concurrent requests with one key therefore
    apply once, and a write that fails part-way leaves no trace, so a retry applies it once."""
    store = store_for_shift(shift_id)
    scoped_key = f"{user.id}:{shift_id}:{idem_key}" if idem_key else None

    def replay() -> dict | None:
        previous = store.get_idempotent(scoped_key) if scoped_key else None
        return None if previous is None else {**previous, "idempotent_replay": True}

    for _ in range(3):
        if (previous := replay()) is not None:
            return previous
        state, version = _load(shift_id, user)
        _check_may_change(state, user)
        if if_match is not None and not if_match_version(if_match, version):
            raise HTTPException(409, f"shift changed (now version {version}); reload and retry")
        if state.ended:
            raise HTTPException(409, f"shift {shift_id} has ended; it can't be changed")
        before = state.model_dump(mode="json")
        try:
            events = action(state)
        except live.ClockBusy as e:
            raise HTTPException(409, f"{e} is driving the clock right now") from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        after = state.model_dump(mode="json")
        if not events and after == before:
            # Nothing changed (e.g. releasing a clock this user doesn't hold): no write, so the
            # version, and every other client's If-Match, stays valid.
            out = {**_view(state, version, store.presence(shift_id)), "events": []}
            if scoped_key:
                store.put_idempotent(scoped_key, out)
            return out
        # The response is stored with the key in the same transaction, so it is built first; the
        # version-checked write makes ``version + 1`` the version it commits, or it fails.
        new_version = version + 1
        out = {**_view(state, new_version, store.presence(shift_id)), "events": events}
        try:
            store.save_shift(
                shift_id,
                after,
                version,
                assignments=live.assignment_rows(state),
                events=[{**e, "version": new_version} for e in events],
                idempotency=(scoped_key, out) if scoped_key else None,
            )
        except DuplicateRequest:
            continue  # a concurrent request with this key committed first: replay its response
        except VersionConflict:
            if if_match is not None:
                raise HTTPException(409, "shift changed concurrently; reload and retry") from None
            continue
        return out
    if (previous := replay()) is not None:
        return previous
    raise HTTPException(409, "shift is busy; retry")


@router.post("")
def create_shift(
    req: CreateShift,
    user: User = Depends(require("dispatcher")),
    _rl: None = Depends(rate_limit("shift", 30, 10, fail_closed=True)),
) -> dict:
    if req.algorithm not in ALGORITHMS:
        raise HTTPException(422, f"unknown algorithm {req.algorithm!r}")
    check_scenario(user, req.scenario)
    state, events = live.start(req.scenario, req.weights, req.algorithm, user.email)
    get_store(state.fab_id).create_shift(
        state.id,
        state.model_dump(mode="json"),
        state.fab_id,
        user.email,
        assignments=live.assignment_rows(state),
        events=[{**e, "version": 1} for e in events],
    )
    return {**_view(state, 1), "events": events}


@router.get("")
def list_shifts(
    fab_id: str = Query(...), limit: int = Query(20, ge=1, le=100), user: User = Depends(require("viewer"))
) -> list[dict]:
    fab_for(user, fab_id)
    return get_store(fab_id).list_shifts(fab_id, limit)


@router.get("/{shift_id}")
def get_shift(shift_id: str, request: Request, user: User = Depends(require("viewer"))):
    """The shift as clients see it. The ETag starts with the shift's version, so it works as an
    If-Match for the write endpoints; the rest of it changes with presence and the clock lease,
    so a conditional GET still picks those up without a version bump."""
    state, version = _load(shift_id, user)
    return etag_json(request, _view(state, version, store_for_shift(shift_id).presence(shift_id)), version=version)


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
    return _mutate(shift_id, user, reporting(user, req.job), if_match, idempotency_key)


def reporting(user: User, job: Job) -> Callable[[live.LiveState], list[dict]]:
    """The action that reports ``job`` on a shift, checked as strictly as a new shift is: the
    job's tool family must exist in the shift's fab, and the shift stays within the size cap."""

    def act(state: live.LiveState) -> list[dict]:
        check_scenario(user, state.scenario.model_copy(update={"jobs": [*state.scenario.jobs, job]}))
        return live.report_job(state, job, user.email)

    return act


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
    return store_for_shift(shift_id).shift_assignments(shift_id)


@router.get("/{shift_id}/events")
def events(
    shift_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(require("viewer")),
) -> list[dict]:
    _load(shift_id, user)
    return store_for_shift(shift_id).events_after(shift_id, after, limit)


@router.post("/{shift_id}/stream-ticket")
def stream_ticket(shift_id: str, user: User = Depends(require("viewer"))) -> dict:
    """A short-lived ticket that opens this shift's stream (``GET .../stream?ticket=``), since
    ``EventSource`` can't send an Authorization header. Bound to the caller and this shift; ask for
    a new one before every (re)connect, and reuse within its lifetime is fine."""
    _load(shift_id, user)
    return {"ticket": issue_stream_ticket(user, shift_id, get_settings()), "expires_in": STREAM_TICKET_TTL_S}


@router.get("/{shift_id}/stream")
async def stream(
    shift_id: str,
    request: Request,
    after: int = Query(0, ge=0, description="resume after this event id (Last-Event-ID wins when sent)"),
    last_event_id: str | None = Header(None),
    user: User = Depends(require("viewer")),
    _rl: None = Depends(rate_limit("stream", 30, 10)),
):
    """Server-Sent Events. The stream tails the shift's event log by id, so it works with
    many server instances and resumes on reconnect (EventSource sends Last-Event-ID).
    Each response closes after ``sse_window_s``, which stays inside serverless limits;
    the browser reconnects on its own. Open streams double as presence heartbeats.

    Authenticate with ``?ticket=`` from ``POST .../stream-ticket`` (``?access_token=`` is
    accepted for one more release and logs a deprecation warning)."""
    await to_thread.run_sync(_load, shift_id, user)
    if not open_streams.acquire(user.id):
        raise HTTPException(
            429,
            f"You already have {open_streams.per_user} live streams open; close one first",
            headers={"Retry-After": str(int(get_settings().sse_window_s))},
        )
    store, settings = store_for_shift(shift_id), get_settings()
    # isascii: "²".isdigit() is True but int("²") raises, which would be a 500.
    valid_header = last_event_id and last_event_id.isascii() and last_event_id.isdigit()
    cursor = int(last_event_id) if valid_header else after

    async def gen():
        nonlocal cursor
        try:
            yield "retry: 1500\n\n"
            deadline = time.monotonic() + settings.sse_window_s
            last_beat = 0.0
            idle = open_streams.poll_floor()
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
                # Once this instance serves many streams, the floor rises to 1 s for all of them.
                idle = open_streams.poll_floor() if batch else min(idle * 1.5, SSE_POLL_MAX_S)
                await asyncio.sleep(0.05 if len(batch) == 100 else idle)
        finally:
            open_streams.release(user.id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
