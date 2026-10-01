"""Application services: the layer between HTTP routes and the solver/store."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .cache import LRU, plan_key
from .config import Settings
from .engine import allocate
from .models import AllocationResult, Scenario, Weights
from .store import Store


@dataclass
class PlanOutcome:
    result: AllocationResult
    cache: str  # "memory" | "store" | "miss"
    elapsed_ms: float


class PlanningService:
    def __init__(self, store: Store, settings: Settings, lru: LRU | None = None):
        self.store, self.settings = store, settings
        self.lru = lru or LRU()

    def _budget(self) -> dict:
        s = self.settings
        return {"alns": s.alns_iterations, "pyvrp": s.pyvrp_iterations, "cap": s.solver_time_limit_s}

    def plan(self, scenario: Scenario, weights: Weights, algorithm: str) -> PlanOutcome:
        t0 = time.perf_counter()
        key = plan_key(
            scenario=scenario.model_dump(mode="json"),
            weights=weights.model_dump(),
            algorithm=algorithm,
            budget=self._budget(),
        )
        if (hit := self.lru.get(key)) is not None:
            return PlanOutcome(AllocationResult.model_validate(hit), "memory", (time.perf_counter() - t0) * 1000)
        if (stored := self.store.get_cached_plan(key)) is not None:
            self.lru.put(key, stored)
            return PlanOutcome(AllocationResult.model_validate(stored), "store", (time.perf_counter() - t0) * 1000)
        result = allocate(scenario, weights, algorithm)
        payload = result.model_dump(mode="json")
        # A plan that hit the time cap isn't reproducible, so don't share it across instances.
        if not result.solver.get("hit_time_cap"):
            self.store.put_cached_plan(key, payload)
        self.lru.put(key, payload)
        return PlanOutcome(result, "miss", (time.perf_counter() - t0) * 1000)
