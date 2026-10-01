"""Fab registry: which sites exist and what each one looks like (floor, families, presets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import User, check_fab, require
from ..fabs import UnknownFab, all_profiles, get_profile
from ..http import etag_json

router = APIRouter(prefix="/api/fabs", tags=["fabs"])


@router.get("")
def list_fabs(request: Request, user: User = Depends(require("viewer"))):
    fabs = [p.public() for p in all_profiles().values() if user.can_access(p.id)]
    return etag_json(request, fabs, max_age=300)


@router.get("/{fab_id}")
def fab(fab_id: str, request: Request, user: User = Depends(require("viewer"))):
    check_fab(user, fab_id)
    try:
        return etag_json(request, get_profile(fab_id).public(), max_age=300)
    except UnknownFab:
        from fastapi import HTTPException

        raise HTTPException(404, f"fab {fab_id} not found") from None
