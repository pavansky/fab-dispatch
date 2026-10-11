"""FastAPI application factory. ``app`` is the ASGI entrypoint for uvicorn and Vercel."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .auth import stream_ticket_secret
from .cache import ENGINE_VERSION
from .config import get_settings
from .help import load_articles
from .http import error_body
from .observability import RequestContext, configure_logging, request_id
from .routes import auth, fabs, help, ingest, live, planning, repairs, system
from .version import APP_VERSION

log = logging.getLogger("fab")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title="Fab Dispatch API",
        version=APP_VERSION,
        description="Allocates equipment engineers to tool-downs and PMs in a semiconductor fab. "
        "Five strategies, from greedy to PyVRP, plus live re-dispatch and a grounded assistant. "
        f"Engine {ENGINE_VERSION}. Sign in at the app, then call the API with the session's bearer token.",
        # Under /api so the same paths work locally and behind Vercel's /api rewrite. The two
        # docs pages are served by routes/system.py, which gives each its own Content-Security-Policy.
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    # The last middleware added is the outermost. CORS goes outside RequestContext, so even the
    # 500 that RequestContext answers for an unhandled error carries CORS headers (otherwise the
    # browser reports an opaque CORS failure instead of the error envelope).
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestContext, hsts=settings.env == "production")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag", "X-Cache", "X-Request-ID", "Server-Timing"],
    )

    # Starlette's HTTPException (FastAPI's subclasses it), so the router's own 404 and 405
    # use the error envelope too.
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        code = {
            401: "unauthorised",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            413: "too_large",
            422: "invalid",
            429: "rate_limited",
            503: "unavailable",
        }.get(exc.status_code, "error")
        return JSONResponse(
            error_body(code, str(exc.detail), request_id.get()),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        msg = f"{where}: {first.get('msg', 'invalid input')}" if where else first.get("msg", "invalid input")
        details = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
        return JSONResponse({**error_body("invalid", msg, request_id.get()), "details": details}, status_code=422)

    for r in (
        system.root,
        system.router,
        auth.router,
        fabs.router,
        planning.router,
        live.router,
        repairs.router,
        help.router,
        ingest.router,
    ):
        app.include_router(r)
    load_articles()  # broken help content (bad link, missing title) fails at startup, not in front of users
    stream_ticket_secret(settings)  # warns at startup, not at the first stream, when tickets are per process
    log.info("fab-dispatch %s ready (env=%s)", ENGINE_VERSION, settings.env)
    return app


app = create_app()
