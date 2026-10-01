"""Repair-history retrieval (Qdrant) and history-based duration prediction."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_repairs, rate_limit
from ..models import SKILLS, Scenario

router = APIRouter(prefix="/api/repairs", tags=["repair history"])


class SimilarRequest(BaseModel):
    family: str
    symptom: str = Field(min_length=3, max_length=500)
    k: int = Field(12, ge=1, le=50)


@router.post("/similar", dependencies=[Depends(rate_limit("repairs", 600, 60))])
def similar(req: SimilarRequest) -> dict:
    if req.family not in SKILLS:
        raise HTTPException(422, f"unknown tool family {req.family!r}")
    return get_repairs().similar(req.family, req.symptom, req.k)


@router.post("/predict-durations", dependencies=[Depends(rate_limit("repairs", 120, 20))])
def predict_durations(scenario: Scenario) -> dict:
    """Replace each tool-down's standard estimate with the history-based prediction.
    PMs keep their scheduled duration. Returns the new scenario and what changed."""
    idx = get_repairs()
    changes, jobs = [], []
    for j in scenario.jobs:
        if j.kind == "down" and j.symptom:
            pred = idx.similar(j.skill, j.symptom)["prediction"]
            if pred:
                minutes = max(15, int(round(pred["minutes"] / 5) * 5))
                changes.append({"job_id": j.id, "standard": j.duration, "predicted": minutes,
                                "p10": pred["p10"], "p90": pred["p90"], "likely_cause": pred["likely_cause"]})
                j = j.model_copy(update={"duration": minutes})
        jobs.append(j)
    return {"scenario": scenario.model_copy(update={"jobs": jobs}), "changes": changes}
