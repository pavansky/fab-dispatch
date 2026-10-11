"""Process-wide singletons, built lazily so imports stay cheap (serverless cold starts)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import cache, lru_cache

from fastapi import HTTPException, Request

from .config import get_settings
from .observability import RateLimiter, client_id
from .services import PlanningService
from .store import Store, create_store, open_store

SHIFT_ID_SEP = "."  # shift ids are "<fab id>.<random>", so a link routes to its fab's database


_opened: list[Store] = []  # every store this process opened, so reset_stores can close them


@lru_cache
def _default_store() -> Store:
    store = create_store(get_settings())
    _opened.append(store)
    return store


@cache
def _tenant_store(fab_id: str) -> Store:
    s = get_settings()
    store = open_store(s.tenant_databases[fab_id], s.db_schema)
    _opened.append(store)
    return store


def get_store(fab_id: str | None = None) -> Store:
    """The store for a fab: its own database if FAB_TENANT_DATABASES lists it, else the default.
    Called without a fab, it's the default database, which holds user-level data."""
    if fab_id is not None and fab_id in get_settings().tenant_databases:
        return _tenant_store(fab_id)
    return _default_store()


def all_stores() -> list[Store]:
    """Every database this deployment writes to: the default plus each fab's own."""
    return [_default_store(), *(_tenant_store(f) for f in sorted(get_settings().tenant_databases))]


def fab_of_shift(shift_id: str) -> str | None:
    return shift_id.split(SHIFT_ID_SEP, 1)[0] if SHIFT_ID_SEP in shift_id else None


def store_for_shift(shift_id: str) -> Store:
    return get_store(fab_of_shift(shift_id))


def reset_stores() -> None:
    """Close and forget every open store (tests that change FAB_TENANT_DATABASES)."""
    while _opened:
        _opened.pop().close()
    _default_store.cache_clear()
    _tenant_store.cache_clear()
    get_planning.cache_clear()


@lru_cache
def get_repairs():
    from .knowledge import RepairIndex

    return RepairIndex(get_settings())


@lru_cache
def get_planning() -> PlanningService:
    return PlanningService(get_store, get_settings())


_limiter = RateLimiter()
log = logging.getLogger("fab")


def rate_limit(name: str, per_min: float, burst: int, fail_closed: bool | Callable[[], bool] = False):
    """Two layers. A token bucket in this instance turns away bursts before any I/O; every
    request it lets through from a signed-in user then costs one database upsert, a per-minute
    counter that holds the quota across every instance (serverless runs many).

    * Unauthenticated calls (help search, equipment ingestion) use the in-memory bucket only: a
      request that cost nothing to authenticate must not cost a database write.
    * If the shared counter can't be reached, a cheap endpoint lets the request through (rate
      limiting must not take the service down with it), while an expensive one (``fail_closed``:
      benchmarks, the optimality gap, starting a shift, an LLM-backed answer) answers 503 with
      Retry-After, since those are exactly the requests a limiter outage would let pile up."""

    def dep(request: Request) -> None:
        s = get_settings()
        if s.env == "test":
            return
        # Per signed-in user where known (fair across shared NAT/proxies), else per client IP.
        user = getattr(request.state, "user", None)
        who = f"user:{user.id}" if user else client_id(request, s.client_ip_header, s.trusted_proxy_hops)
        if not _limiter.allow(who, name, per_min, burst):
            raise HTTPException(429, f"Too many {name} requests; slow down.", headers={"Retry-After": "5"})
        if user is None:
            return  # anonymous: the in-memory bucket only, never a database write per request
        try:
            hits = get_store().hit_rate(f"{name}:{who}", 60)
        except Exception as e:
            closed = fail_closed() if callable(fail_closed) else fail_closed
            log.warning(
                "shared rate limit unavailable (%s); %s", type(e).__name__, "refusing" if closed else "allowing"
            )
            if closed:
                raise HTTPException(
                    503, f"The {name} quota can't be checked right now; retry shortly.", headers={"Retry-After": "30"}
                ) from None
            return
        if hits > per_min + burst:
            raise HTTPException(429, f"Too many {name} requests; slow down.", headers={"Retry-After": "30"})

    return dep
