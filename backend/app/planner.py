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


class Planner:
    def __init__(self, scenario: Scenario, weights: Weights):
        self.scenario = scenario
        self.w = weights
        self.techs: dict[str, Engineer] = {t.id: t for t in scenario.engineers}
        self.jobs: dict[str, Job] = {j.id: j for j in scenario.jobs}
        self.routes: dict[str, list[str]] = {t: [] for t in self.techs}
        self._speed = scenario.settings.walk_m_per_min
        self._sims: dict[str, RouteSim] = {t: self._simulate(t, [])[0] for t in self.techs}  # type: ignore[misc]
        self._ins_cache: dict[tuple[str, str], Insertion] = {}

    # ------------------------------------------------------------------ geometry
    def metres(self, a: str, b: str) -> float:
        pa = self.techs.get(a) or self.jobs[a]
        pb = self.techs.get(b) or self.jobs[b]
        return abs(pa.x - pb.x) + abs(pa.y - pb.y)

    # ------------------------------------------------------------------ simulation
    def _simulate(self, tech_id: str, route: list[str]) -> tuple[RouteSim | None, str | None]:
        """Walk the route from the home bay; return the timing or the first hard violation."""
        tech = self.techs[tech_id]
        t, here = float(tech.shift_start), tech_id
        starts, arrivals, ends, legs = [], [], [], []
        wait = 0.0
        overq = 0
        for jid in route:
            job = self.jobs[jid]
            d = self.metres(here, jid)
            arrival = t + d / self._speed
            if arrival > job.latest:
                return None, WINDOW_MISSED
            start = max(arrival, job.earliest)
            wait += start - arrival
            overq += tech.skills[job.skill] - job.min_level
            t, here = start + job.duration, jid
            arrivals.append(arrival)
            starts.append(start)
            ends.append(t)
            legs.append(d)
            if t > tech.shift_end:
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
        for pos in range(len(route) + 1):
            sim, why = self._simulate(tech_id, route[:pos] + [job_id] + route[pos:])
            if sim is None:
                fails[why] += 1  # type: ignore[index]
                continue
            after = self._soft(sim)
            breakdown = {k: round(after[k] - before[k], 2) for k in after}
            breakdown["workload"] = self.w.workload_balance * len(route)
            breakdown["priority"] = -self.w.priority_reward * job.priority
            cost = sum(breakdown.values())
            if best is None or cost < best.cost:
                best = Insertion(tech_id, job_id, True, None, pos, cost, breakdown)
        if best is None:
            return Insertion(tech_id, job_id, False, fails.most_common(1)[0][0])
        return best

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

    def sim(self, tech_id: str) -> RouteSim:
        return self._sims[tech_id]

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
