"""Domain model: equipment maintenance in a 300mm semiconductor fab.

Engineers (resources) start the shift in a home bay, are certified on tool families at
a level 1..3, and work a 12-hour shift. Jobs (requests) are unplanned tool-downs or
scheduled preventive maintenance (PM) on a tool at a floor position; each needs one
tool family at a minimum level, carries a priority, and must *start* inside a window.
Times are minutes since shift start; positions are metres on the fab floor plan.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# Tool families are defined per fab (app/fabs/profiles/*.json), so a skill is any family id.
Skill = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]


class Engineer(BaseModel):
    id: str
    name: str
    x: float = Field(description="metres east on the floor plan")
    y: float = Field(description="metres north on the floor plan")
    skills: dict[Skill, int] = Field(description="tool family -> certification level 1..3")
    shift_start: int = 0
    shift_end: int = 12 * 60
    max_jobs: int = 5

    @model_validator(mode="after")
    def _check(self) -> Engineer:
        if self.shift_end <= self.shift_start:
            raise ValueError(f"{self.id}: shift_end must be after shift_start")
        if any(not 1 <= lvl <= 3 for lvl in self.skills.values()):
            raise ValueError(f"{self.id}: skill levels must be 1..3")
        return self


class Job(BaseModel):
    id: str
    x: float = Field(description="metres east on the floor plan")
    y: float = Field(description="metres north on the floor plan")
    skill: Skill
    min_level: int = Field(1, ge=1, le=3)
    priority: int = Field(2, ge=1, le=3, description="1 PM, 2 tool down, 3 bottleneck tool down")
    kind: Literal["down", "pm"] = "down"
    earliest: int = Field(description="earliest start, minutes")
    latest: int = Field(description="latest start, minutes")
    duration: int = Field(60, gt=0)
    tool: str = ""
    symptom: str = Field("", description="free-text fault description, used for repair-history retrieval")

    @property
    def reported_at(self) -> int:
        """When the job becomes known: PMs are on the schedule from shift start,
        tool-downs are reported when their window opens."""
        return 0 if self.kind == "pm" else self.earliest

    @model_validator(mode="after")
    def _check(self) -> Job:
        if self.latest < self.earliest:
            raise ValueError(f"{self.id}: latest must be >= earliest")
        return self


class Weights(BaseModel):
    """Soft-constraint weights. Everything is expressed in 'cost points'."""

    travel_100m: float = Field(4.0, ge=0, description="per 100 m walked on the floor")
    wait_min: float = Field(0.2, ge=0, description="per minute idle before a window opens")
    overqualification: float = Field(8.0, ge=0, description="per level above the job's need")
    workload_balance: float = Field(5.0, ge=0, description="per job the engineer already holds")
    priority_reward: float = Field(60.0, ge=0, description="reward per priority point served")
    stability: float = Field(25.0, ge=0, description="live mode: per job moved to a different engineer on re-plan")


class Settings(BaseModel):
    walk_m_per_min: float = Field(60.0, gt=0, description="walking speed in cleanroom garb")
    floor_width: float = 400.0
    floor_height: float = 240.0


class Scenario(BaseModel):
    fab_id: str = Field("fab1-300mm-logic", description="which fab profile this shift belongs to")
    engineers: list[Engineer]
    jobs: list[Job]
    settings: Settings = Settings()

    @model_validator(mode="after")
    def _unique_ids(self) -> Scenario:
        for kind, items in (("engineer", self.engineers), ("job", self.jobs)):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {kind} ids")
        return self


class Candidate(BaseModel):
    tech_id: str
    cost: float


class Assignment(BaseModel):
    job_id: str
    tech_id: str
    sequence: int
    arrival: float
    start: float
    end: float
    travel_m: float
    cost: float
    cost_breakdown: dict[str, float]
    explanation: str
    alternatives: list[Candidate] = []
    rejections: dict[str, int] = {}


class Unassigned(BaseModel):
    job_id: str
    reason: str
    rejections: dict[str, int]


class RouteStop(BaseModel):
    job_id: str
    arrival: float
    start: float
    end: float
    locked: bool = False


class Route(BaseModel):
    tech_id: str
    stops: list[RouteStop]
    metres: float
    end_time: float


class AllocationResult(BaseModel):
    algorithm: str
    label: str
    assignments: list[Assignment]
    unassigned: list[Unassigned]
    routes: list[Route]
    metrics: dict[str, float]
    solver: dict = Field(default_factory=dict, description="search statistics, e.g. iterations")
