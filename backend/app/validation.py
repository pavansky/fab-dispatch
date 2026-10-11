"""Cross-checks that need a fab profile, so the request models can stay profile-agnostic."""

from __future__ import annotations

from fastapi import HTTPException

from .auth import User, check_fab
from .config import get_settings
from .fabs import FabProfile, UnknownFab, get_profile
from .models import Scenario


def fab_for(user: User, fab_id: str) -> FabProfile:
    check_fab(user, fab_id)
    try:
        return get_profile(fab_id)
    except UnknownFab:
        raise HTTPException(404, f"fab {fab_id} not found") from None


def check_scenario(user: User, sc: Scenario) -> FabProfile:
    """The scenario belongs to a fab the user can see, and only uses that fab's tool families."""
    profile = fab_for(user, sc.fab_id)
    s = get_settings()
    if len(sc.jobs) > s.max_jobs or len(sc.engineers) > s.max_engineers:
        raise HTTPException(
            413,
            f"scenario too large for this deployment: at most {s.max_engineers} engineers and {s.max_jobs} jobs "
            f"(got {len(sc.engineers)} x {len(sc.jobs)}); set FAB_MAX_ENGINEERS and FAB_MAX_JOBS to raise the limit",
        )
    families = set(profile.family_ids)
    unknown = {j.skill for j in sc.jobs} | {s for e in sc.engineers for s in e.skills}
    unknown -= families
    if unknown:
        raise HTTPException(422, f"tool families {sorted(unknown)} are not defined for {profile.id}")
    return profile
