"""Structured logging, request IDs, timing, security headers and a rate limiter."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
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

# The API serves JSON and event streams, which no browser renders, so its CSP allows nothing: a
# response that somehow rendered as HTML (a content-type bug, an old browser sniffing) could run
# no script and could not be framed. The interactive docs set their own (see ``docs_csp``).
API_CSP = "default-src 'self'; frame-ancestors 'none'"
HSTS = "max-age=63072000; includeSubDomains; preload"  # the same value vercel.json sends for the web app
# Case-insensitive and attribute-tolerant, so a <SCRIPT> or <script type=...> is hashed too; one
# that slipped past would be blocked by the policy, never run (CodeQL "bad HTML filtering").
_INLINE_SCRIPT = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script[^>]*>", re.S | re.I)


def docs_csp(html: str) -> str:
    """The policy for FastAPI's bundled Swagger UI and ReDoc pages: scripts and styles from
    cdn.jsdelivr.net, the FastAPI favicon, Google Fonts (ReDoc), ReDoc's search worker (a blob), and
    the one inline bootstrap script, pinned by hash rather than by 'unsafe-inline'. Nothing else."""
    hashes = " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode()}'"
        for m in _INLINE_SCRIPT.finditer(html)
    )
    return (
        "default-src 'self'; "
        f"script-src 'self' https://cdn.jsdelivr.net{' ' + hashes if hashes else ''}; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "connect-src 'self'; worker-src blob:; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    )


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
    security headers on every response.

    ``hsts`` (set in production) sends Strict-Transport-Security on every response; otherwise it is
    sent only on responses that arrived over HTTPS (so a plain-HTTP local run never pins its host)."""

    def __init__(self, app, hsts: bool = False):
        super().__init__(app)
        self.hsts = hsts

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
        response.headers.setdefault("Content-Security-Policy", API_CSP)  # the docs pages set their own
        if self.hsts or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = HSTS
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
