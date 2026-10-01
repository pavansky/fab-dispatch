from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .algorithms import ALGORITHMS
from .engine import allocate
from .generator import AREAS, PRESETS, generate
from .models import AllocationResult, Scenario, Weights

app = FastAPI(title="Fab Maintenance Allocation Engine", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class GenerateRequest(BaseModel):
    seed: int = 7
    n_engineers: int = Field(14, ge=1, le=60)
    n_jobs: int = Field(45, ge=1, le=200)
    preset: str = "normal"


class AllocateRequest(BaseModel):
    scenario: Scenario
    weights: Weights = Weights()
    algorithms: list[str] = list(ALGORITHMS)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "algorithms": {k: label for k, (label, _) in ALGORITHMS.items()},
        "presets": {k: {"label": p.label, "description": p.description} for k, p in PRESETS.items()},
        "areas": AREAS,
        "default_weights": Weights().model_dump(),
    }


@app.post("/api/scenario", response_model=Scenario)
def make_scenario(req: GenerateRequest) -> Scenario:
    if req.preset not in PRESETS:
        raise HTTPException(422, f"unknown preset {req.preset!r}")
    return generate(req.seed, req.n_engineers, req.n_jobs, req.preset)


@app.post("/api/allocate", response_model=list[AllocationResult])
def run(req: AllocateRequest) -> list[AllocationResult]:
    unknown = [a for a in req.algorithms if a not in ALGORITHMS]
    if unknown:
        raise HTTPException(422, f"unknown algorithm(s): {unknown}")
    return [allocate(req.scenario, req.weights, a) for a in req.algorithms]
