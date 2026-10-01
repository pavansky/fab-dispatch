from fastapi import APIRouter, Request

from ..algorithms import ALGORITHMS
from ..cache import ENGINE_VERSION
from ..config import get_settings
from ..deps import get_planning, get_store
from ..generator import AREAS, PRESETS
from ..http import etag_json
from ..models import Weights

router = APIRouter(prefix="/api", tags=["system"])

ALGO_INFO = {
    "greedy": {"family": "constructive", "speed": "instant"},
    "hungarian": {"family": "assignment", "speed": "instant"},
    "regret": {"family": "constructive", "speed": "instant"},
    "alns": {"family": "metaheuristic", "speed": "~1 s"},
    "pyvrp": {"family": "metaheuristic", "speed": "~1 s"},
}


@router.get("/livez", include_in_schema=False)
def livez() -> dict:
    """Process is up. Cheap: no dependencies touched."""
    return {"status": "ok"}


@router.get("/health")
def health() -> dict:
    """Readiness: can we reach the store? Public output stays minimal."""
    try:
        db_ok = get_store().ping()
    except Exception:  # noqa: BLE001 - health must report, not raise
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db_ok": db_ok, "version": ENGINE_VERSION}


@router.get("/meta")
def meta(request: Request):
    s = get_settings()
    payload = {
        "version": ENGINE_VERSION,
        "algorithms": {k: {"label": label, **ALGO_INFO.get(k, {})} for k, (label, _) in ALGORITHMS.items()},
        "presets": {k: {"label": p.label, "description": p.description} for k, p in PRESETS.items()},
        "areas": AREAS,
        "default_weights": Weights().model_dump(),
        "store": get_store().kind,
        "vector_index": "qdrant-server" if s.qdrant_url else "qdrant-embedded",
        "solver_budget": {"alns_iterations": s.alns_iterations, "pyvrp_iterations": s.pyvrp_iterations,
                          "time_cap_s": s.solver_time_limit_s},
    }
    return etag_json(request, payload, max_age=300, public=True)


@router.get("/cache/stats", include_in_schema=False)
def cache_stats() -> dict:
    return get_planning().lru.stats()
