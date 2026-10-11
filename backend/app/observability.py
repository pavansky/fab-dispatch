"""Structured logging, request IDs, timing, security headers and a rate limiter."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

request_id: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("fab")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: str, as_json: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if as_json else logging.Formatter("%(asctime)s %(levelname)-5s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # our middleware logs requests instead


class RequestContext(BaseHTTPMiddleware):
    """Request ID (honours an incoming X-Request-ID), access log, Server-Timing and
    security headers on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"fields": {"path": request.url.path}})
            response = JSONResponse(
                {"error": {"code": "internal", "message": "Internal error", "request_id": rid}}, status_code=500
            )
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("Server-Timing", f"app;dur={ms:.1f}")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path != "/api/livez":
            log.info(
                "%s %s %s %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                ms,
                extra={
                    "fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "ms": round(ms, 1),
                    }
                },
            )
        request_id.reset(token)
        return response


class RateLimiter:
    """Token bucket per (client, bucket name). In-memory, so on serverless each instance
    limits on its own: a guard against runaway clients, not a quota system.

    Buckets are kept least recently used first and evicted once idle for ``idle_s`` (by then
    every limit in this app has refilled to its burst, so forgetting the bucket changes
    nothing) or when there are more than ``max_buckets`` (memory stays bounded however many
    distinct clients turn up)."""

    def __init__(self, max_buckets: int = 10_000, idle_s: float = 600.0, clock: Callable[[], float] = time.monotonic):
        self._buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()
        self._max, self._idle_s, self._clock = max_buckets, idle_s, clock
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._buckets)

    def allow(self, client: str, name: str, rate_per_min: float, burst: int) -> bool:
        now = self._clock()
        key = (client, name)
        with self._lock:
            tokens, last = self._buckets.pop(key, (float(burst), now))
            tokens = min(burst, tokens + (now - last) * rate_per_min / 60)
            allowed = tokens >= 1
            self._buckets[key] = (tokens - 1 if allowed else tokens, now)  # now the most recent
            while self._buckets:
                _, (_, oldest) = next(iter(self._buckets.items()))
                if len(self._buckets) <= self._max and now - oldest < self._idle_s:
                    break
                self._buckets.popitem(last=False)
            return allowed


def client_id(request: Request, ip_header: str | None = None, proxy_hops: int = 0) -> str:
    """The caller's address, for per-client rate limits. Forwarding headers are trusted only as
    configured, because a client can send any X-Forwarded-For it likes (and so get a fresh
    bucket per request if its leftmost entry were believed):

    * ``ip_header``: a header the platform itself sets to the client IP, which clients can't
      supply (Vercel: ``x-vercel-forwarded-for``; Cloudflare: ``cf-connecting-ip``);
    * ``proxy_hops``: how many of our own proxies append to X-Forwarded-For; the client is the
      entry that many places from the right (what the outermost proxy saw). Entries further
      left were written by the client;
    * otherwise the socket peer."""
    if ip_header and (value := request.headers.get(ip_header, "").split(",")[-1].strip()):
        return value
    if proxy_hops:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= proxy_hops:
            return hops[-proxy_hops]
    return request.client.host if request.client else "unknown"
