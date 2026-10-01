"""Repair-history retrieval (Qdrant) and history-based duration prediction, per fab."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import User, require
from ..config import get_settings
from ..deps import get_repairs, rate_limit
from ..models import Scenario
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api/repairs", tags=["repair history"])


class SimilarRequest(BaseModel):
    fab_id: str | None = None
    family: str
    symptom: str = Field(min_length=3, max_length=500)
    k: int = Field(12, ge=1, le=50)


@router.post("/similar")
def similar(
    req: SimilarRequest, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("repairs", 600, 60))
) -> dict:
    profile = fab_for(user, req.fab_id or get_settings().default_fab)
    if req.family not in profile.family_ids:
        raise HTTPException(422, f"unknown tool family {req.family!r} for {profile.id}")
    return get_repairs().similar(profile, req.family, req.symptom, req.k)


@router.post("/predict-durations")
def predict_durations(
    scenario: Scenario, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("repairs", 120, 20))
) -> dict:
    """Replace each tool-down's standard estimate with the history-based prediction.
    PMs keep their scheduled duration. Returns the new scenario and what changed."""
    profile = check_scenario(user, scenario)
    idx = get_repairs()
    changes, jobs = [], []
    for j in scenario.jobs:
        if j.kind == "down" and j.symptom:
            pred = idx.similar(profile, j.skill, j.symptom)["prediction"]
            if pred:
                minutes = max(15, int(round(pred["minutes"] / 5) * 5))
                changes.append(
                    {
                        "job_id": j.id,
                        "standard": j.duration,
                        "predicted": minutes,
                        "p10": pred["p10"],
                        "p90": pred["p90"],
                        "likely_cause": pred["likely_cause"],
                    }
                )
                j = j.model_copy(update={"duration": minutes})
        jobs.append(j)
    return {"scenario": scenario.model_copy(update={"jobs": jobs}), "changes": changes}
