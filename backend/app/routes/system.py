"""Health, metadata, and operational endpoints."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from ..algorithms import ALGORITHMS
from ..cache import ENGINE_VERSION
from ..config import get_settings
from ..deps import all_stores, get_planning, get_store
from ..http import etag_json
from ..models import Weights
from ..version import APP_VERSION, COMMIT

router = APIRouter(prefix="/api", tags=["system"])

ALGO_INFO = {
    "greedy": {"family": "constructive", "speed": "instant"},
    "hungarian": {"family": "assignment", "speed": "instant"},
    "regret": {"family": "constructive", "speed": "instant"},
    "alns": {"family": "metaheuristic", "speed": "~0.2 s"},
    "pyvrp": {"family": "metaheuristic", "speed": "~0.4 s"},
}


root = APIRouter(include_in_schema=False)


@root.get("/")
def index() -> dict:
    """Someone opening the API port in a browser gets directions, not a 404."""
    return {
        "service": "fab-dispatch API",
        "release": APP_VERSION,
        "version": ENGINE_VERSION,
        "docs": "/api/docs",
        "health": "/api/health",
        "ui": "run `npm run dev` in frontend/ and open http://localhost:5173",
    }


@router.get("/livez", include_in_schema=False)
def livez() -> dict:
    """Process is up. Cheap: no dependencies touched."""
    return {"status": "ok"}


@router.get("/health")
def health() -> dict:
    """Readiness: can we reach the store, and is its schema current? Output stays minimal."""
    from ..store import SCHEMA_VERSION

    db_ok = schema_ok = True
    stores = 0
    try:
        for store in all_stores():  # the default database and every fab's own
            stores += 1
            db_ok = db_ok and store.ping()
            schema_ok = schema_ok and store.schema_version() >= SCHEMA_VERSION
    except Exception:  # health must report, not raise
        db_ok = schema_ok = False
    return {
        "status": "ok" if db_ok and schema_ok else "degraded",
        "db_ok": db_ok,
        "schema_ok": schema_ok,
        "databases": stores,
        "version": ENGINE_VERSION,
        "release": APP_VERSION,
        "commit": COMMIT,
        "env": get_settings().env,
    }


@router.post("/internal/prune", include_in_schema=False)
def prune(authorization: str | None = Header(None)) -> dict:
    """Data retention, called daily by the platform scheduler (Vercel Cron sends
    ``Authorization: Bearer $CRON_SECRET``). Refused unless a secret is configured."""
    secret = get_settings().cron_secret
    if not secret or not hmac.compare_digest(authorization or "", f"Bearer {secret}"):
        raise HTTPException(401, "unauthorised")
    deleted: dict[str, int] = {}
    for store in all_stores():
        for table, n in store.prune().items():
            deleted[table] = deleted.get(table, 0) + n
    return {"deleted": deleted}


@router.get("/meta")
def meta(request: Request):
    s = get_settings()
    payload = {
        "version": ENGINE_VERSION,
        "release": APP_VERSION,
        "commit": COMMIT,
        "algorithms": {k: {"label": label, **ALGO_INFO.get(k, {})} for k, (label, _) in ALGORITHMS.items()},
        "default_fab": s.default_fab,
        "auth_mode": s.auth_mode,
        "default_weights": Weights().model_dump(),
        "store": get_store().kind,
        "fab_databases": sorted(get_settings().tenant_databases),
        "vector_index": "qdrant-server" if s.qdrant_url else "qdrant-disk" if s.qdrant_path else "exact",
        "solver_budget": {
            "alns_iterations": s.alns_iterations,
            "pyvrp_iterations": s.pyvrp_iterations,
            "time_cap_s": s.solver_time_limit_s,
        },
    }
    return etag_json(request, payload, max_age=300, public=True)


@router.get("/cache/stats", include_in_schema=False)
def cache_stats() -> dict:
    return get_planning().lru.stats()
