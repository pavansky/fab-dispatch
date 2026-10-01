"""Live shift: dispatch that keeps working as the shift unfolds.

The clock moves forward (driven by the client or an operator, so no server process has
to stay alive, which is what serverless needs). Tool-downs are reported at their
``reported_at`` time, and engineers can be pulled off shift. On every event the shift
is **re-planned on a rolling horizon**:

* work already started is frozen on its engineer; everyone resumes from the current clock
* only jobs known *so far* are planned (no peeking at future tool-downs)
* moving a job away from the engineer who held it costs ``Weights.stability``, so a new
  tool-down changes as few people's plans as possible

Each change appends events to the shift's event log, which the SSE stream relays to
every open dashboard.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .config import get_settings
from .engine import allocate
from .fabs import get_profile
from .models import AllocationResult, Job, Scenario, Weights
from .planner import Frozen

CLOCK_LEASE_S = 20  # a dispatcher driving the clock holds it this long after their last tick


class ClockBusy(Exception):
    """Another dispatcher is driving this shift's clock."""


class LiveState(BaseModel):
    id: str
    created_at: str
    scenario: Scenario  # every job, including ones not reported yet
    weights: Weights
    algorithm: str
    clock: float = 0.0
    released: list[str] = Field(default_factory=list)
    off_shift: dict[str, float] = Field(default_factory=dict)
    plan: AllocationResult | None = None
    replans: int = 0
    ended: bool = False
    created_by: str = ""
    driver: str | None = None  # who holds the clock lease
    driver_until: float = 0.0  # epoch seconds; the lease lapses on its own

    @property
    def fab_id(self) -> str:
        return self.scenario.fab_id

    @property
    def shift_length(self) -> int:
        return get_profile(self.scenario.fab_id).shift.length_min

    def known_jobs(self) -> list[Job]:
        released = set(self.released)
        return [j for j in self.scenario.jobs if j.id in released]


def _event(kind: str, state: LiveState, message: str, actor: str = "system", **data) -> dict:
    return {
        "kind": kind,
        "clock": round(state.clock, 1),
        "message": message,
        "data": data,
        "actor": actor,
        "at": datetime.now(UTC).isoformat(),
    }


def claim_clock(state: LiveState, actor: str) -> None:
    """One driver at a time: two dispatchers pressing Play must not double the speed."""
    now = time.time()
    if state.driver and state.driver != actor and state.driver_until > now:
        raise ClockBusy(state.driver)
    state.driver, state.driver_until = actor, now + CLOCK_LEASE_S


def release_clock(state: LiveState, actor: str) -> list[dict]:
    if state.driver == actor:
        state.driver, state.driver_until = None, 0.0
        return [_event("clock_released", state, f"{actor} paused the clock.", actor)]
    return []


def start(scenario: Scenario, weights: Weights, algorithm: str, actor: str = "system") -> tuple[LiveState, list[dict]]:
    state = LiveState(
        id=uuid.uuid4().hex[:12],
        created_at=datetime.now(UTC).isoformat(),
        scenario=scenario,
        weights=weights,
        algorithm=algorithm,
        created_by=actor,
    )
    state.released = [j.id for j in scenario.jobs if j.reported_at <= 0]
    events = [
        _event(
            "shift_started",
            state,
            f"{actor} started the shift with {len(state.released)} known jobs and {len(scenario.engineers)} engineers.",
            actor,
        )
    ]
    events += _replan(state, "shift start", actor)
    return state, events


def advance(state: LiveState, minutes: float, actor: str = "system") -> list[dict]:
    """Move the clock forward, re-planning at every tool-down reported on the way."""
    if state.ended:
        return []
    claim_clock(state, actor)
    target = min(state.shift_length, state.clock + max(0.0, minutes))
    released = set(state.released)
    arrivals = sorted(
        (j for j in state.scenario.jobs if j.id not in released and j.reported_at <= target),
        key=lambda j: (j.reported_at, j.id),
    )
    events: list[dict] = []
    for when in sorted({j.reported_at for j in arrivals}):
        batch = [j for j in arrivals if j.reported_at == when]
        state.clock = max(state.clock, float(when))
        state.released += [j.id for j in batch]
        for j in batch:
            events.append(
                _event(
                    "job_reported",
                    state,
                    f"{j.id} reported: {j.tool} "
                    f"({'bottleneck ' if j.priority == 3 else ''}{'PM' if j.kind == 'pm' else 'tool down'}).",
                    job_id=j.id,
                    priority=j.priority,
                )
            )
        events += _replan(state, f"{len(batch)} new job(s)", actor)
    state.clock = target
    events.append(_event("clock", state, f"Clock at {state.clock:.0f} min.", actor, **progress(state)))
    if state.clock >= state.shift_length:
        state.ended = True
        state.driver, state.driver_until = None, 0.0
        events.append(_event("shift_ended", state, "Shift ended.", actor, **progress(state)))
    return events


def report_job(state: LiveState, job: Job, actor: str = "system") -> list[dict]:
    """An operator reports a tool-down right now."""
    if any(j.id == job.id for j in state.scenario.jobs):
        raise ValueError(f"job id {job.id} already exists")
    window = job.latest - job.earliest
    job = job.model_copy(update={"earliest": int(state.clock), "latest": int(state.clock) + window})
    state.scenario = state.scenario.model_copy(update={"jobs": [*state.scenario.jobs, job]})
    state.released.append(job.id)
    events = [
        _event(
            "job_reported",
            state,
            f"{job.id} reported by {actor}: {job.tool}.",
            actor,
            job_id=job.id,
            priority=job.priority,
        )
    ]
    return events + _replan(state, f"{job.id} reported", actor)


def engineer_off(state: LiveState, engineer_id: str, actor: str = "system") -> list[dict]:
    if engineer_id not in {e.id for e in state.scenario.engineers}:
        raise ValueError(f"unknown engineer {engineer_id}")
    if engineer_id in state.off_shift:
        return []
    state.off_shift[engineer_id] = state.clock
    events = [
        _event(
            "engineer_off",
            state,
            f"{actor} took {engineer_id} off shift; their open work is redistributed.",
            actor,
            engineer_id=engineer_id,
        )
    ]
    return events + _replan(state, f"{engineer_id} off shift", actor)


def job_status(state: LiveState) -> dict[str, str]:
    """done | in_progress | planned | unassigned for every known job."""
    status = {j: "unassigned" for j in state.released}
    if state.plan:
        for route in state.plan.routes:
            for s in route.stops:
                status[s.job_id] = (
                    "done" if s.end <= state.clock else "in_progress" if s.start <= state.clock else "planned"
                )
    return status


def progress(state: LiveState) -> dict:
    st = job_status(state)
    counts = {k: sum(1 for v in st.values() if v == k) for k in ("done", "in_progress", "planned", "unassigned")}
    return {**counts, "known": len(st), "total": len(state.scenario.jobs)}


def _replan(state: LiveState, reason: str, actor: str = "system") -> list[dict]:
    before = {a.job_id: a.tech_id for a in state.plan.assignments} if state.plan else {}
    frozen: dict[str, Frozen] = {}
    if state.plan:
        for route in state.plan.routes:
            started = [s.job_id for s in route.stops if s.start <= state.clock]
            frozen[route.tech_id] = Frozen(route=started, not_before=state.clock)
    for eid in state.off_shift:
        frozen.setdefault(eid, Frozen(not_before=state.clock))

    # Engineers who left finish what they started, then take nothing new.
    engineers = []
    for e in state.scenario.engineers:
        if e.id in state.off_shift:
            last_end = max(
                (
                    s.end
                    for r in (state.plan.routes if state.plan else [])
                    if r.tech_id == e.id
                    for s in r.stops
                    if s.start <= state.clock
                ),
                default=state.clock,
            )
            e = e.model_copy(update={"shift_end": max(e.shift_start + 1, int(max(last_end, state.clock)))})
        engineers.append(e)
    scenario = state.scenario.model_copy(update={"engineers": engineers})

    plan = allocate(
        scenario,
        state.weights,
        state.algorithm,
        frozen=frozen,
        open_jobs=set(state.released),
        time_limit_s=get_settings().live_time_limit_s,
        previous_owner=before,
    )
    after = {a.job_id: a.tech_id for a in plan.assignments}
    moved = sorted(j for j in before if j in after and after[j] != before[j])
    newly = sorted(j for j in after if j not in before)
    dropped = sorted(j for j in before if j not in after)
    state.plan = plan
    state.replans += 1
    msg = (
        f"Re-planned ({reason}) with {plan.label}: {len(newly)} newly assigned, "
        f"{len(moved)} moved between engineers, {len(dropped)} dropped, {len(plan.unassigned)} unassigned."
    )
    return [
        _event(
            "replanned",
            state,
            msg,
            actor,
            moved=moved,
            newly_assigned=newly,
            dropped=dropped,
            runtime_ms=plan.metrics["runtime_ms"],
            assignments={j: after[j] for j in newly},
        )
    ]
