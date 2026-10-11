"""Health, metadata, and operational endpoints."""

from __future__ import annotations

import hmac
import logging
import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from starlette.responses import HTMLResponse

from ..algorithms import ALGORITHMS
from ..auth import User, require
from ..cache import ENGINE_VERSION
from ..config import get_settings
from ..deps import all_stores, get_planning, get_repairs, get_store
from ..http import etag_json
from ..models import Weights
from ..observability import docs_csp
from ..version import APP_VERSION, COMMIT

router = APIRouter(prefix="/api", tags=["system"])
log = logging.getLogger("fab")
HEALTH_CACHE_S = 10.0  # one check per instance per 10 s, however often /health is called
_health: dict = {}
_health_lock = threading.Lock()

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


def _docs_page(html: HTMLResponse) -> HTMLResponse:
    """A docs page with the policy that allows exactly what it loads (RequestContext leaves a CSP
    a route set alone, and gives every other response the no-script API policy)."""
    html.headers["Content-Security-Policy"] = docs_csp(html.body.decode())
    return html


@root.get("/api/docs", include_in_schema=False)
def swagger_ui() -> HTMLResponse:
    # No OAuth2 flow here (bearer tokens come from the app), so no redirect page is linked.
    return _docs_page(
        get_swagger_ui_html(openapi_url="/api/openapi.json", title="Fab Dispatch API", oauth2_redirect_url=None)
    )


@root.get("/api/redoc", include_in_schema=False)
def redoc() -> HTMLResponse:
    return _docs_page(get_redoc_html(openapi_url="/api/openapi.json", title="Fab Dispatch API"))


@router.get("/livez", include_in_schema=False)
def livez() -> dict:
    """Process is up. Cheap: no dependencies touched."""
    return {"status": "ok"}


def _check_databases() -> tuple[bool, bool, int]:
    """(reachable, schema current, how many) over the default database and every fab's own.
    One query per database (reading the schema version proves the connection too), on the
    store's own connection: SQLite keeps one open and Postgres reuses its idle ones."""
    from ..store import SCHEMA_VERSION

    settings = get_settings()
    db_ok = schema_ok = True
    try:
        stores = all_stores()
    except Exception as e:  # a database that can't even be opened: health must report, not raise
        log.warning("health: opening the databases failed (%s)", type(e).__name__)
        return False, False, 1 + len(settings.tenant_databases)
    for store in stores:
        try:
            schema_ok = store.schema_version() >= SCHEMA_VERSION and schema_ok
        except Exception as e:
            log.warning("health: a %s database is unreachable (%s)", store.kind, type(e).__name__)
            db_ok = schema_ok = False
    return db_ok, schema_ok, len(stores)


@router.get("/health")
def health() -> dict:
    """Readiness: can we reach every database, and is each schema current? Public and
    unauthenticated, so the result is cached per instance for ``HEALTH_CACHE_S``: a client
    polling it can't make this instance query every tenant database on each call. Output
    stays minimal (a count of databases, never their names)."""
    s = get_settings()
    key = (s.database_url, tuple(sorted(s.tenant_databases.items())))
    now = time.monotonic()
    with _health_lock:
        if _health.get("key") != key or now - _health.get("at", -HEALTH_CACHE_S) >= HEALTH_CACHE_S:
            _health.update(key=key, at=now, result=_check_databases())
        db_ok, schema_ok, stores = _health["result"]
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


def _vector_index() -> str:
    """The repair index's actual mode (it falls back to memory when the Qdrant folder is locked,
    and ignores FAB_QDRANT_PATH in tests), not one guessed from settings."""
    try:
        return get_repairs().mode
    except Exception as e:  # e.g. the Qdrant client can't be built; /meta must still answer
        log.warning("meta: repair index unavailable (%s)", type(e).__name__)
        return "unavailable"


@router.get("/meta")
def meta(request: Request):
    """Public (the sign-in screen reads it), so it describes the deployment, never its tenants:
    no fab or database names."""
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
        "vector_index": _vector_index(),
        "solver_budget": {
            "alns_iterations": s.alns_iterations,
            "pyvrp_iterations": s.pyvrp_iterations,
            "time_cap_s": s.solver_time_limit_s,
        },
    }
    return etag_json(request, payload, max_age=300, public=True)


@router.get("/cache/stats", include_in_schema=False)
def cache_stats(_: User = Depends(require("viewer"))) -> dict:
    return get_planning().lru.stats()
