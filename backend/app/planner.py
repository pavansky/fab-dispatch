"""Route state plus the hard/soft constraint engine shared by every algorithm.

Each engineer owns an ordered route of jobs, starting from their home bay. Walking
distance is Manhattan distance: fab bays are laid out on a grid of aisles, so you
can't cut diagonally across tools.
Algorithms only ever ask two questions:

* ``best_insertion(tech, job)`` - the cheapest feasible position for ``job`` in the
  tech's current route, with its marginal cost, or the hard constraint that rules it out.
* ``commit(...)`` - apply that insertion.

Because every algorithm uses the same feasibility check and cost function, their results
are directly comparable: the only difference is the *order* and *scope* of decisions.

Serving a job is optional. ``total_cost`` charges the reward of every unserved job, so an
insertion's cost already nets that reward off: a cost >= 0 means the detour (plus workload
and stability) costs more than serving the job earns, and the plan is cheaper without it.
So every method commits an insertion only when its cost is < 0, exactly as the exact
solver is free to leave a money-losing job out.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import Engineer, Job, Scenario, Weights

# Hard-constraint failure codes, in the order they are checked.
SKILL_MISSING = "skill_missing"
LEVEL_TOO_LOW = "level_too_low"
AT_CAPACITY = "at_capacity"
WINDOW_MISSED = "window_missed"
SHIFT_OVERRUN = "shift_overrun"

REASON_TEXT = {
    SKILL_MISSING: "lacks the skill",
    LEVEL_TOO_LOW: "certification too low",
    AT_CAPACITY: "already at max jobs",
    WINDOW_MISSED: "cannot arrive inside the time window",
    SHIFT_OVERRUN: "would run past shift end",
}


@dataclass
class RouteSim:
    starts: list[float]
    arrivals: list[float]
    ends: list[float]
    legs_m: list[float]
    wait_min: float
    overqualification: int
    end_time: float

    @property
    def metres(self) -> float:
        return sum(self.legs_m)


@dataclass
class Insertion:
    tech_id: str
    job_id: str
    feasible: bool
    reason: str | None = None
    position: int = -1
    cost: float = float("inf")
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class Frozen:
    """Live-shift state for one engineer: jobs already started can't move, and new
    work can't start before ``not_before`` (the current shift clock).

    ``starts`` and ``arrivals`` record when each started job actually began and when the
    engineer reached it. Started work is history: a re-plan replays those times rather
    than re-deriving them from shift start, which would forget the "not before now" delay
    that applied when the job was planned and could double-book the engineer."""

    route: list[str] = field(default_factory=list)
    not_before: float = 0.0
    starts: list[float] = field(default_factory=list)
    arrivals: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.starts) > len(self.route) or len(self.arrivals) > len(self.starts):
            raise ValueError("recorded times must cover a prefix of the started route")


class Planner:
    def __init__(
        self,
        scenario: Scenario,
        weights: Weights,
        frozen: dict[str, Frozen] | None = None,
        open_jobs: set[str] | None = None,
        time_limit_s: float | None = None,
        previous_owner: dict[str, str] | None = None,
    ):
        self.scenario = scenario
        self.w = weights
        self.techs: dict[str, Engineer] = {t.id: t for t in scenario.engineers}
        self.jobs: dict[str, Job] = {j.id: j for j in scenario.jobs}
        self.frozen: dict[str, Frozen] = {t: (frozen or {}).get(t, Frozen()) for t in self.techs}
        locked = {j for f in self.frozen.values() for j in f.route}
        # Jobs the algorithms may place. Defaults to everything not already locked in.
        candidates = set(self.jobs) if open_jobs is None else set(open_jobs)
        self.open_jobs: dict[str, Job] = {j: self.jobs[j] for j in sorted(candidates - locked)}
        self.routes: dict[str, list[str]] = {t: list(self.frozen[t].route) for t in self.techs}
        self._speed = scenario.settings.walk_m_per_min
        self._sims: dict[str, RouteSim] = {}
        for t in self.techs:
            sim, why = self._simulate(t, self.routes[t])
            if sim is None:
                raise ValueError(f"frozen route for {t} is infeasible: {why}")
            self._sims[t] = sim
        self._ins_cache: dict[tuple[str, str], Insertion] = {}
        self.meta: dict = {}
        self.time_limit_s = time_limit_s  # search budget override (live mode uses a shorter one)
        # Live re-plans: who held each job in the previous plan. Moving it costs w.stability,
        # so a new tool-down doesn't reshuffle every engineer's afternoon.
        self.previous_owner = previous_owner or {}

    # ------------------------------------------------------------------ geometry
    def metres(self, a: str, b: str) -> float:
        pa = self.techs.get(a) or self.jobs[a]
        pb = self.techs.get(b) or self.jobs[b]
        return abs(pa.x - pb.x) + abs(pa.y - pb.y)

    # ------------------------------------------------------------------ simulation
    def _simulate(self, tech_id: str, route: list[str]) -> tuple[RouteSim | None, str | None]:
        """Walk the route from the home bay; return the timing or the first hard violation.

        An engineer leaves the home bay just in time for their first job, so any slack
        before it is spent at the bay, not idle at a tool: no idle wait is charged before
        the first stop (its ``arrival`` is still the earliest the engineer could be there).
        From the second stop on, arriving before a window opens is idle wait. Every strategy
        and the exact solver cost routes through this one simulation, so they all share the
        rule."""
        tech = self.techs[tech_id]
        frozen = self.frozen[tech_id]
        t, here = float(tech.shift_start), tech_id
        starts, arrivals, ends, legs = [], [], [], []
        wait = 0.0
        overq = 0
        for i, jid in enumerate(route):
            if i == len(frozen.route):
                t = max(t, frozen.not_before)  # open work starts no earlier than "now"
            job = self.jobs[jid]
            d = self.metres(here, jid)
            if i < len(frozen.starts):
                # Started work: replay the recorded times, it already happened.
                start = frozen.starts[i]
                arrival = frozen.arrivals[i] if i < len(frozen.arrivals) else min(t + d / self._speed, start)
            else:
                arrival = t + d / self._speed
                if arrival > job.latest:
                    return None, WINDOW_MISSED
                start = max(arrival, job.earliest)
            if i > 0:  # slack before the first job is spent at the bay, not idle at a tool
                wait += start - arrival
            overq += tech.skills[job.skill] - job.min_level
            t, here = start + job.duration, jid
            arrivals.append(arrival)
            starts.append(start)
            ends.append(t)
            legs.append(d)
            if t > tech.shift_end and i >= len(frozen.route):
                return None, SHIFT_OVERRUN
        return RouteSim(starts, arrivals, ends, legs, wait, overq, t), None

    def _soft(self, sim: RouteSim) -> dict[str, float]:
        return {
            "travel": self.w.travel_100m * sim.metres / 100,
            "waiting": self.w.wait_min * sim.wait_min,
            "overqualification": self.w.overqualification * sim.overqualification,
        }

    # ------------------------------------------------------------------ queries
    def best_insertion(self, tech_id: str, job_id: str) -> Insertion:
        key = (tech_id, job_id)
        if key not in self._ins_cache:
            self._ins_cache[key] = self._best_insertion(tech_id, job_id)
        return self._ins_cache[key]

    def _best_insertion(self, tech_id: str, job_id: str) -> Insertion:
        tech, job, route = self.techs[tech_id], self.jobs[job_id], self.routes[tech_id]
        if job.skill not in tech.skills:
            return Insertion(tech_id, job_id, False, SKILL_MISSING)
        if tech.skills[job.skill] < job.min_level:
            return Insertion(tech_id, job_id, False, LEVEL_TOO_LOW)
        if len(route) >= tech.max_jobs:
            return Insertion(tech_id, job_id, False, AT_CAPACITY)

        before = self._soft(self._sims[tech_id])
        best: Insertion | None = None
        fails: Counter[str] = Counter()
        for pos in range(len(self.frozen[tech_id].route), len(route) + 1):
            sim, why = self._simulate(tech_id, route[:pos] + [job_id] + route[pos:])
            if sim is None:
                fails[why] += 1  # type: ignore[index]
                continue
            cost, breakdown = self._marginal(tech_id, job_id, before, sim)
            if best is None or cost < best.cost:
                best = Insertion(tech_id, job_id, True, None, pos, cost, breakdown)
        if best is None:
            return Insertion(tech_id, job_id, False, fails.most_common(1)[0][0])
        return best

    def _marginal(
        self, tech_id: str, job_id: str, before: dict[str, float], sim: RouteSim
    ) -> tuple[float, dict[str, float]]:
        """Exact change in ``total_cost`` from adding ``job_id`` to the route (giving
        ``sim``), plus its breakdown rounded for display. The cost is summed unrounded, so
        it equals the ``total_cost`` delta, not the sum of the displayed parts."""
        after = self._soft(sim)
        parts = {k: after[k] - before[k] for k in after}
        parts["workload"] = self.w.workload_balance * len(self.routes[tech_id])
        parts["priority"] = -self.w.priority_reward * self.jobs[job_id].priority
        moved = self._moved(tech_id, job_id)
        if moved:
            parts["reassignment"] = moved
        return sum(parts.values()), {k: round(v, 2) for k, v in parts.items()}

    def scan(self, job_id: str, tech_ids: list[str] | None = None) -> tuple[list[Insertion], Counter[str]]:
        """All feasible insertions for a job (cheapest first) and why the rest failed."""
        feasible, rejected = [], Counter()
        for tid in tech_ids or self.techs:
            ins = self.best_insertion(tid, job_id)
            if ins.feasible:
                feasible.append(ins)
            else:
                rejected[ins.reason] += 1
        feasible.sort(key=lambda i: i.cost)
        return feasible, rejected

    # ------------------------------------------------------------------ mutation
    def commit(self, ins: Insertion) -> None:
        assert ins.feasible
        route = self.routes[ins.tech_id]
        route.insert(ins.position, ins.job_id)
        sim, why = self._simulate(ins.tech_id, route)
        assert sim is not None, why
        self._sims[ins.tech_id] = sim
        for key in [k for k in self._ins_cache if k[0] == ins.tech_id or k[1] == ins.job_id]:
            del self._ins_cache[key]

    def append(self, tech_id: str, job_id: str) -> Insertion | None:
        """Put a job at the end of a route (used to replay an external solver's
        sequence). Returns None if that breaks a hard constraint."""
        tech, route = self.techs[tech_id], self.routes[tech_id]
        if self.tech_can_do(tech_id, job_id) is not None or len(route) >= tech.max_jobs:
            return None
        sim, _ = self._simulate(tech_id, route + [job_id])
        if sim is None:
            return None
        cost, breakdown = self._marginal(tech_id, job_id, self._soft(self._sims[tech_id]), sim)
        ins = Insertion(tech_id, job_id, True, None, len(route), cost, breakdown)
        self.commit(ins)
        return ins

    def _moved(self, tech_id: str, job_id: str) -> float:
        prev = self.previous_owner.get(job_id)
        return self.w.stability if prev is not None and prev != tech_id else 0.0

    def remove(self, job_id: str) -> str:
        """Take an open job off its route (frozen work can't be removed). Returns the engineer."""
        for tid, route in self.routes.items():
            if job_id in route:
                idx = route.index(job_id)
                if idx < len(self.frozen[tid].route):
                    raise ValueError(f"{job_id} is frozen on {tid}")
                route.pop(idx)
                self._refresh(tid)
                return tid
        raise KeyError(job_id)

    def snapshot(self) -> dict[str, tuple[str, ...]]:
        return {t: tuple(r) for t, r in self.routes.items()}

    def restore(self, snap: dict[str, tuple[str, ...]]) -> None:
        for tid, route in snap.items():
            if tuple(self.routes[tid]) != route:
                self.routes[tid] = list(route)
                self._refresh(tid)

    def _refresh(self, tech_id: str) -> None:
        sim, why = self._simulate(tech_id, self.routes[tech_id])
        assert sim is not None, why
        self._sims[tech_id] = sim
        for key in [k for k in self._ins_cache if k[0] == tech_id]:
            del self._ins_cache[key]

    def total_cost(self) -> float:
        """The full objective every search method minimises: route soft costs, the convex
        workload term each insertion pays, the reward forgone for every unserved job and,
        in live re-plans, the stability cost of every job moved to a different engineer."""
        return sum(self.cost_parts().values())

    def cost_parts(self) -> dict[str, float]:
        """``total_cost`` split into its terms: ``operating`` (walking, waiting,
        over-qualification and the reward forgone for unserved jobs), ``workload`` (the
        convex balance term, w*k(k-1)/2 per engineer) and ``reassignment`` (stability)."""
        placed = self.assigned_jobs()
        operating = sum(self.route_soft_cost(tid) for tid in self.routes)
        operating += sum(self.w.priority_reward * j.priority for jid, j in self.open_jobs.items() if jid not in placed)
        workload = sum(self.w.workload_balance * len(r) * (len(r) - 1) / 2 for r in self.routes.values())
        reassignment = sum(self._moved(tid, j) for tid, r in self.routes.items() for j in r)
        return {"operating": operating, "workload": workload, "reassignment": reassignment}

    def tech_can_do(self, tech_id: str, job_id: str) -> str | None:
        tech, job = self.techs[tech_id], self.jobs[job_id]
        if job.skill not in tech.skills:
            return SKILL_MISSING
        if tech.skills[job.skill] < job.min_level:
            return LEVEL_TOO_LOW
        return None

    def clone(self) -> Planner:
        """Independent copy with the same committed routes (for warm starts and search)."""
        other = Planner.__new__(Planner)
        other.__dict__.update(self.__dict__)
        other.routes = {t: list(r) for t, r in self.routes.items()}
        other.open_jobs = dict(self.open_jobs)
        other._sims = dict(self._sims)
        other._ins_cache = dict(self._ins_cache)
        other.meta = {}
        return other

    def sim(self, tech_id: str) -> RouteSim:
        return self._sims[tech_id]

    def unplaced(self) -> list[str]:
        """Open jobs not yet on any route, in stable order."""
        placed = self.assigned_jobs()
        return [j for j in self.open_jobs if j not in placed]

    def assigned_jobs(self) -> set[str]:
        return {j for r in self.routes.values() for j in r}

    def route_soft_cost(self, tech_id: str) -> float:
        if not self.routes[tech_id]:
            return 0.0
        return sum(self._soft(self._sims[tech_id]).values())


def describe_rejections(rejected: Counter[str]) -> str:
    if not rejected:
        return "no engineers rejected"
    parts = [f"{n} {REASON_TEXT[r]}" for r, n in rejected.most_common()]
    return "rejected: " + ", ".join(parts)
