from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..algorithms import ALGORITHMS
from ..algorithms.exact import TooLarge, run_exact
from ..deps import get_planning, rate_limit
from ..engine import allocate
from ..generator import PRESETS, generate
from ..models import AllocationResult, Scenario, Weights
from ..planner import Planner

router = APIRouter(prefix="/api", tags=["planning"])


class GenerateRequest(BaseModel):
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
    preset: str = "normal"
    seeds: int = Field(10, ge=1, le=30)
    n_engineers: int = Field(14, ge=1, le=60)
    n_jobs: int = Field(45, ge=1, le=120)
    weights: Weights = Weights()
    algorithms: list[str] = Field(default_factory=lambda: list(ALGORITHMS))


class GapRequest(BaseModel):
    seeds: int = Field(5, ge=1, le=10)
    n_engineers: int = Field(4, ge=1, le=6)
    n_jobs: int = Field(12, ge=1, le=16)
    preset: str = "normal"
    weights: Weights = Weights()


def _check_algos(names: list[str]) -> None:
    unknown = [a for a in names if a not in ALGORITHMS]
    if unknown:
        raise HTTPException(422, f"unknown algorithm(s): {unknown}")


def _check_preset(name: str) -> None:
    if name not in PRESETS:
        raise HTTPException(422, f"unknown preset {name!r}")


def _check_size(sc: Scenario) -> None:
    if len(sc.jobs) > 200 or len(sc.engineers) > 60:
        raise HTTPException(413, "scenario too large: at most 60 engineers and 200 jobs")


@router.post("/scenario", response_model=Scenario)
def make_scenario(req: GenerateRequest) -> Scenario:
    _check_preset(req.preset)
    return generate(req.seed, req.n_engineers, req.n_jobs, req.preset)


@router.post("/plan", response_model=AllocationResult, dependencies=[Depends(rate_limit("plan", 240, 40))])
def plan(req: PlanRequest, response: Response) -> AllocationResult:
    """Plan one shift with one strategy. Cached by content: identical requests are instant."""
    _check_algos([req.algorithm])
    _check_size(req.scenario)
    out = get_planning().plan(req.scenario, req.weights, req.algorithm)
    response.headers["X-Cache"] = out.cache
    response.headers["Server-Timing"] = f"plan;desc={out.cache};dur={out.elapsed_ms:.1f}"
    return out.result


@router.post("/allocate", response_model=list[AllocationResult], dependencies=[Depends(rate_limit("plan", 240, 40))])
def allocate_many(req: AllocateRequest) -> list[AllocationResult]:
    """Every requested strategy on the same shift (the UI calls /plan per strategy instead,
    so fast ones render first)."""
    _check_algos(req.algorithms)
    _check_size(req.scenario)
    svc = get_planning()
    return [svc.plan(req.scenario, req.weights, a).result for a in req.algorithms]


@router.post("/benchmark", dependencies=[Depends(rate_limit("benchmark", 20, 6))])
def benchmark(req: BenchmarkRequest) -> dict:
    """All strategies over many seeded shifts of one preset. The client calls it once per
    preset, so each request stays well inside serverless time limits."""
    _check_preset(req.preset)
    _check_algos(req.algorithms)
    svc = get_planning()
    runs = []
    for seed in range(req.seeds):
        sc = generate(seed, req.n_engineers, req.n_jobs, req.preset)
        for algo in req.algorithms:
            runs.append({"preset": req.preset, "seed": seed, "algorithm": algo,
                         "metrics": svc.plan(sc, req.weights, algo).result.metrics})
    return {"preset": req.preset, "runs": runs}


@router.post("/optimality-gap", dependencies=[Depends(rate_limit("benchmark", 20, 6))])
def optimality_gap(req: GapRequest) -> dict:
    """Exact optimum (route enumeration + MILP) vs every heuristic, on small shifts."""
    _check_preset(req.preset)
    rows = []
    for seed in range(req.seeds):
        sc = generate(seed, req.n_engineers, req.n_jobs, req.preset)
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
        rows.append({"seed": seed, "optimum": round(optimum, 2), "costs": {k: round(v, 2) for k, v in costs.items()},
                     "gap_pct": {k: round(100 * (v - optimum) / abs(optimum), 2) if optimum else 0.0
                                 for k, v in costs.items()}})
    mean_gap = {a: round(statistics.fmean(r["gap_pct"][a] for r in rows), 2) for a in ALGORITHMS}
    return {"rows": rows, "mean_gap_pct": mean_gap,
            "note": "Gap = (heuristic cost - proven optimum) / |optimum|, on the full objective incl. unserved penalty."}


__all__ = ["allocate", "router"]
