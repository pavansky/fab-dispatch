"""HTTP helpers: ETag responses for cacheable GETs."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response


def etag_json(request: Request, payload: Any, max_age: int = 0, public: bool = False) -> Response:
    """JSON with a strong ETag; answers 304 when the client already has this version."""
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":"), sort_keys=True).encode()
    tag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    cache = f"{'public' if public else 'private'}, max-age={max_age}, must-revalidate"
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": cache})
    return Response(body, media_type="application/json", headers={"ETag": tag, "Cache-Control": cache})


def error_body(code: str, message: str, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


__all__ = ["etag_json", "error_body", "JSONResponse"]
