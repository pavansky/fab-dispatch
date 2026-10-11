from __future__ import annotations

import statistics
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from ..algorithms import ALGORITHMS
from ..auth import User, require
from ..config import get_settings
from ..deps import get_planning, rate_limit
from ..engine import allocate
from ..generator import generate
from ..models import AllocationResult, Scenario, Weights
from ..planner import Planner
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api", tags=["planning"])

# Benchmark work is bounded by seeds x jobs. The slowest admitted request (8 seeds of 120 jobs,
# 60 engineers, all five strategies) takes ~25 s on a laptop with the production solver budgets,
# well inside the 60 s serverless limit (vercel.json maxDuration); the unbounded worst case
# (30 x 120) took ~95 s.
BENCHMARK_MAX_JOB_RUNS = 1000


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))  # keeps the caller's order


# At most one entry per strategy (duplicates dropped), each a short name: an unbounded list made
# one rate-limited request plan the same shift thousands of times.
AlgorithmNames = Annotated[
    list[Annotated[str, StringConstraints(max_length=40)]],
    Field(min_length=1, max_length=len(ALGORITHMS)),
    AfterValidator(_unique),
]


def check_size(n_engineers: int, n_jobs: int) -> None:
    """The configured ceiling (FAB_MAX_ENGINEERS / FAB_MAX_JOBS): a plain 422 with the limit in it,
    so a local run that wants 1000 x 1000 knows which setting to raise."""
    s = get_settings()
    if n_engineers > s.max_engineers or n_jobs > s.max_jobs:
        raise ValueError(
            f"shift too large for this deployment: at most {s.max_engineers} engineers and {s.max_jobs} jobs "
            f"(got {n_engineers} x {n_jobs}); set FAB_MAX_ENGINEERS and FAB_MAX_JOBS to raise the limit"
        )


class GenerateRequest(BaseModel):
    fab_id: str | None = None
    seed: int = Field(7, ge=0, le=1_000_000)
    n_engineers: int = Field(14, ge=1)
    n_jobs: int = Field(45, ge=1)
    preset: str = "normal"

    @model_validator(mode="after")
    def _within_limits(self) -> GenerateRequest:
        check_size(self.n_engineers, self.n_jobs)
        return self


class PlanRequest(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithm: str = "pyvrp"

    @model_validator(mode="after")
    def _within_limits(self) -> PlanRequest:
        check_size(len(self.scenario.engineers), len(self.scenario.jobs))
        return self


class AllocateRequest(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithms: AlgorithmNames = Field(default_factory=lambda: list(ALGORITHMS))

    @model_validator(mode="after")
    def _within_limits(self) -> AllocateRequest:
        check_size(len(self.scenario.engineers), len(self.scenario.jobs))
        return self


class BenchmarkRequest(BaseModel):
    fab_id: str | None = None
    preset: str = "normal"
    seeds: int = Field(10, ge=1, le=30)
    n_engineers: int = Field(14, ge=1)
    n_jobs: int = Field(45, ge=1)
    weights: Weights = Weights()
    algorithms: AlgorithmNames = Field(default_factory=lambda: list(ALGORITHMS))

    @model_validator(mode="after")
    def _bounded(self) -> BenchmarkRequest:
        check_size(self.n_engineers, self.n_jobs)
        if self.seeds * self.n_jobs > BENCHMARK_MAX_JOB_RUNS:
            raise ValueError(
                f"benchmark too large: seeds x n_jobs must be at most {BENCHMARK_MAX_JOB_RUNS} "
                f"(got {self.seeds} x {self.n_jobs}); use fewer seeds or split it into several requests"
            )
        return self


class GapRequest(BaseModel):
    fab_id: str | None = None
    seeds: int = Field(5, ge=1, le=10)
    n_engineers: int = Field(4, ge=1, le=6)
    n_jobs: int = Field(12, ge=1, le=16)
    preset: str = "normal"
    weights: Weights = Weights()


def _check_algos(names: list[str]) -> None:
    unknown = [a for a in names if a not in ALGORITHMS]
    if unknown:
        raise HTTPException(422, f"unknown algorithm(s): {unknown}")


def _profile_and_preset(user: User, fab_id: str | None, preset: str):
    profile = fab_for(user, fab_id or get_settings().default_fab)
    if preset not in profile.presets:
        raise HTTPException(422, f"unknown preset {preset!r} for {profile.id}")
    return profile


@router.post("/scenario", response_model=Scenario)
def make_scenario(req: GenerateRequest, user: User = Depends(require("viewer"))) -> Scenario:
    profile = _profile_and_preset(user, req.fab_id, req.preset)
    return generate(req.seed, req.n_engineers, req.n_jobs, req.preset, profile.id)


@router.post("/plan", response_model=AllocationResult)
def plan(
    req: PlanRequest,
    response: Response,
    user: User = Depends(require("viewer")),
    _rl: None = Depends(rate_limit("plan", 240, 40)),
) -> AllocationResult:
    """Plan one shift with one strategy. Cached by content: identical requests are instant."""
    _check_algos([req.algorithm])
    check_scenario(user, req.scenario)
    out = get_planning().plan(req.scenario, req.weights, req.algorithm)
    response.headers["X-Cache"] = out.cache
    response.headers["Server-Timing"] = f"plan;desc={out.cache};dur={out.elapsed_ms:.1f}"
    return out.result


@router.post("/allocate", response_model=list[AllocationResult])
def allocate_many(
    req: AllocateRequest, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("plan", 240, 40))
) -> list[AllocationResult]:
    """Every requested strategy on the same shift (the UI calls /plan per strategy instead,
    so fast ones render first)."""
    _check_algos(req.algorithms)
    check_scenario(user, req.scenario)
    svc = get_planning()
    return [svc.plan(req.scenario, req.weights, a).result for a in req.algorithms]


@router.post("/benchmark")
def benchmark(
    req: BenchmarkRequest,
    user: User = Depends(require("dispatcher")),
    _rl: None = Depends(rate_limit("benchmark", 20, 6, fail_closed=True)),
) -> dict:
    """All strategies over many seeded shifts of one preset. Each request is capped at
    ``seeds x n_jobs <= 1000`` (BENCHMARK_MAX_JOB_RUNS), which keeps the slowest admitted case
    to roughly 25 s against a 60 s serverless limit; the client calls it once per preset."""
    profile = _profile_and_preset(user, req.fab_id, req.preset)
    _check_algos(req.algorithms)
    svc = get_planning()
    runs = []
    for seed in range(req.seeds):
        sc = generate(seed, req.n_engineers, req.n_jobs, req.preset, profile.id)
        for algo in req.algorithms:
            runs.append(
                {
                    "preset": req.preset,
                    "seed": seed,
                    "algorithm": algo,
                    "metrics": svc.plan(sc, req.weights, algo).result.metrics,
                }
            )
    return {"fab_id": profile.id, "preset": req.preset, "runs": runs}


@router.post("/optimality-gap")
def optimality_gap(
    req: GapRequest,
    user: User = Depends(require("dispatcher")),
    _rl: None = Depends(rate_limit("benchmark", 20, 6, fail_closed=True)),
) -> dict:
    """Exact optimum (route enumeration + MILP) vs every heuristic, on small shifts."""
    from ..algorithms.exact import TooLarge, run_exact  # SciPy's MILP: loaded only for this endpoint

    profile = _profile_and_preset(user, req.fab_id, req.preset)
    rows = []
    for seed in range(req.seeds):
        sc = generate(seed, req.n_engineers, req.n_jobs, req.preset, profile.id)
        p = Planner(sc, req.weights)
        try:
            run_exact(p)
        except TooLarge as e:
            raise HTTPException(422, str(e)) from e
        optimum = p.total_cost()
        costs = {}
        for algo in ALGORITHMS:
            q = Planner(sc, req.weights)
            ALGORITHMS[algo][1](q)
            costs[algo] = q.total_cost()
        rows.append(
            {
                "seed": seed,
                "optimum": round(optimum, 2),
                "costs": {k: round(v, 2) for k, v in costs.items()},
                "gap_pct": {
                    k: round(100 * (v - optimum) / abs(optimum), 2) if optimum else 0.0 for k, v in costs.items()
                },
            }
        )
    mean_gap = {a: round(statistics.fmean(r["gap_pct"][a] for r in rows), 2) for a in ALGORITHMS}
    return {
        "rows": rows,
        "mean_gap_pct": mean_gap,
        "note": "Gap = (heuristic cost - proven optimum) / |optimum|, on the full objective incl. unserved penalty.",
    }


__all__ = ["allocate", "router"]
