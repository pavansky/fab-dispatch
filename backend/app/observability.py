"""Structured logging, request IDs, timing, security headers and a rate limiter."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
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
    limits on its own: a guard against runaway clients, not a quota system."""

    def __init__(self):
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, name: str, rate_per_min: float, burst: int) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get((client, name), (float(burst), now))
            tokens = min(burst, tokens + (now - last) * rate_per_min / 60)
            if tokens < 1:
                self._buckets[(client, name)] = (tokens, now)
                return False
            self._buckets[(client, name)] = (tokens - 1, now)
            return True


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
