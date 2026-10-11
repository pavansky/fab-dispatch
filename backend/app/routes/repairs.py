"""Repair-history retrieval (Qdrant) and history-based duration estimates, per fab."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import User, require
from ..config import get_settings
from ..deps import get_repairs, rate_limit
from ..models import Scenario
from ..validation import check_scenario, fab_for

router = APIRouter(prefix="/api/repairs", tags=["repair history"])

# What /predict-durations does, for the UI to show next to the toggle. Its accuracy against
# the standard estimate is measured by scripts/duration_study.py.
PREDICTION_BASIS = (
    "Each tool-down's standard estimate (the fault code's catalogue mean) is replaced by the "
    "similarity-weighted mean of the most similar past repairs. That helps when the symptom "
    "points to a root cause; otherwise it stays close to the fault code's average. "
    "p10-p90 is the middle 80% of those past repairs' actual times."
)


class SimilarRequest(BaseModel):
    fab_id: str | None = None
    family: str
    symptom: str = Field(min_length=3, max_length=500)
    k: int = Field(12, ge=1, le=50)
    roster: list[str] | None = Field(
        None,
        max_length=500,
        description="engineer ids on shift; when given, experienced_engineers lists only these",
    )


@router.post("/similar")
def similar(
    req: SimilarRequest, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("repairs", 600, 60))
) -> dict:
    profile = fab_for(user, req.fab_id or get_settings().default_fab)
    if req.family not in profile.family_ids:
        raise HTTPException(422, f"unknown tool family {req.family!r} for {profile.id}")
    return get_repairs().similar(profile, req.family, req.symptom, req.k, roster=req.roster)


@router.post("/predict-durations")
def predict_durations(
    scenario: Scenario, user: User = Depends(require("viewer")), _rl: None = Depends(rate_limit("repairs", 120, 20))
) -> dict:
    """Replace each tool-down's standard estimate with the history-based estimate (k-NN mean).
    PMs keep their scheduled duration. Returns the new scenario, what changed (with each
    estimate's p10-p90 band, likely cause and basis) and a plain-language ``basis``."""
    profile = check_scenario(user, scenario)
    idx = get_repairs()
    roster = [e.id for e in scenario.engineers]
    changes, jobs = [], []
    for j in scenario.jobs:
        if j.kind == "down" and j.symptom:
            found = idx.similar(profile, j.skill, j.symptom, roster=roster)
            pred = found["prediction"]
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
                        "cause_share": pred["cause_share"],
                        "neighbours": pred["neighbours"],
                        "basis": "knn_mean",
                        "experienced_engineers": found["experienced_engineers"],
                    }
                )
                j = j.model_copy(update={"duration": minutes})
        jobs.append(j)
    return {"scenario": scenario.model_copy(update={"jobs": jobs}), "changes": changes, "basis": PREDICTION_BASIS}
