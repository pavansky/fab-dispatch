"""Process-wide singletons, built lazily so imports stay cheap (serverless cold starts)."""
from __future__ import annotations

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


def rate_limit(name: str, per_min: float, burst: int):
    def dep(request: Request) -> None:
        if get_settings().env == "test":
            return
        if not _limiter.allow(client_id(request), name, per_min, burst):
            raise HTTPException(429, f"Too many {name} requests; slow down.", headers={"Retry-After": "5"})
    return dep
