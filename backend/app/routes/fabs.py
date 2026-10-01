"""Fab registry: which sites exist and what each one looks like (floor, families, presets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..auth import User, check_fab, require
from ..deps import get_store
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


@router.get("/{fab_id}/engineers/{engineer_id}/assignments")
def engineer_assignments(
    fab_id: str, engineer_id: str, limit: int = Query(100, ge=1, le=500), user: User = Depends(require("viewer"))
) -> list[dict]:
    """What an engineer has been given across this fab's live shifts, newest first: a query on
    the assignments read model, not a scan of shift documents."""
    check_fab(user, fab_id)
    return get_store().engineer_assignments(fab_id, engineer_id, limit)
