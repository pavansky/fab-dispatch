"""Process-wide singletons, built lazily so imports stay cheap (serverless cold starts)."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import HTTPException, Request

from .config import get_settings
from .observability import RateLimiter, client_id
from .services import PlanningService
from .store import Store, create_store


@lru_cache
def get_store() -> Store:
    return create_store(get_settings())


@lru_cache
def get_repairs():
    from .knowledge import RepairIndex

    return RepairIndex(get_settings())


@lru_cache
def get_planning() -> PlanningService:
    return PlanningService(get_store(), get_settings())


_limiter = RateLimiter()
log = logging.getLogger("fab")


def rate_limit(name: str, per_min: float, burst: int):
    """Two layers. A token bucket in this instance absorbs bursts with no I/O; a per-minute
    counter in the database holds the quota across every instance (serverless runs many).
    If the database can't be reached the request is allowed: rate limiting must not take
    the service down with it."""

    def dep(request: Request) -> None:
        if get_settings().env == "test":
            return
        # Per signed-in user where known (fair across shared NAT/proxies), else per client IP.
        user = getattr(request.state, "user", None)
        who = f"user:{user.id}" if user else client_id(request)
        if not _limiter.allow(who, name, per_min, burst):
            raise HTTPException(429, f"Too many {name} requests; slow down.", headers={"Retry-After": "5"})
        try:
            hits = get_store().hit_rate(f"{name}:{who}", 60)
        except Exception as e:
            log.warning("shared rate limit unavailable (%s); allowing", type(e).__name__)
            return
        if hits > per_min + burst:
            raise HTTPException(429, f"Too many {name} requests; slow down.", headers={"Retry-After": "30"})

    return dep
