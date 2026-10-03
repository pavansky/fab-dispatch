from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

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


class GenerateRequest(BaseModel):
    fab_id: str | None = None
    seed: int = Field(7, ge=0, le=1_000_000)
    n_engineers: int = Field(14, ge=1, le=60)
    n_jobs: int = Field(45, ge=1, le=200)
    preset: str = "normal"


class PlanRequest(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithm: str = "pyvrp"


class AllocateRequest(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithms: list[str] = Field(default_factory=lambda: list(ALGORITHMS))


class BenchmarkRequest(BaseModel):
    fab_id: str | None = None
    preset: str = "normal"
    seeds: int = Field(10, ge=1, le=30)
    n_engineers: int = Field(14, ge=1, le=60)
    n_jobs: int = Field(45, ge=1, le=120)
    weights: Weights = Weights()
    algorithms: list[str] = Field(default_factory=lambda: list(ALGORITHMS))


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
    _rl: None = Depends(rate_limit("benchmark", 20, 6)),
) -> dict:
    """All strategies over many seeded shifts of one preset. The client calls it once per
    preset, so each request stays well inside serverless time limits."""
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
    req: GapRequest, user: User = Depends(require("dispatcher")), _rl: None = Depends(rate_limit("benchmark", 20, 6))
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
