"""HTTP helpers: ETag responses for cacheable GETs, and If-Match for versioned writes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response


def etag_json(
    request: Request, payload: Any, max_age: int = 0, public: bool = False, version: int | None = None
) -> Response:
    """JSON with a strong ETag; answers 304 when the client already has this representation.
    With ``version`` (a versioned resource such as a live shift) the tag is
    ``"<version>-<digest>"``: the version makes it usable as an If-Match for writes
    (see ``if_match_version``), and the digest of the whole body keeps a conditional GET
    honest about parts that change without a new version (presence, the clock lease)."""
    # Keep key order (e.g. a fab's presets are listed in the order the profile defines them).
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":")).encode()
    digest = hashlib.sha256(body).hexdigest()
    tag = f'"{version}-{digest[:16]}"' if version is not None else f'"{digest[:32]}"'
    cache = f"{'public' if public else 'private'}, max-age={max_age}, must-revalidate"
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": cache})
    return Response(body, media_type="application/json", headers={"ETag": tag, "Cache-Control": cache})


def if_match_version(if_match: str, version: int) -> bool:
    """Does an If-Match header pin this version? Accepts ``*``, the ETag a GET returned
    (``"<version>-<digest>"``), a quoted ``"<version>"`` or a bare version number, and a
    comma-separated list of them. Only the version is compared: the write is checked against
    the shift's state, not against who happened to be watching when the client read it."""
    for raw in if_match.split(","):
        tag = raw.strip()
        if tag == "*":
            return True
        tag = tag.removeprefix("W/").strip('"')  # a proxy that compresses may weaken the tag
        if tag.split("-", 1)[0] == str(version):
            return True
    return False


def error_body(code: str, message: str, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


__all__ = ["JSONResponse", "error_body", "etag_json", "if_match_version"]
