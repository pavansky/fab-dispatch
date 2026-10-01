"""Fab profiles: everything fab-specific lives in data, not code.

A profile describes one site: the floor plan, the tool families (with their areas,
tool-ID prefix and fault catalogue), the shift, walking speed, and the scenario presets
used for planning drills. Onboarding a new fab is adding a JSON file to
``profiles/`` (or to ``FAB_PROFILES_DIR``). The schema below validates it at startup,
so a broken profile fails the deploy, not a dispatcher at 3 a.m.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

PROFILES_DIR = Path(__file__).parent / "profiles"


class FaultCause(BaseModel):
    cause: str
    fix: str
    mean_min: int = Field(gt=0)
    sd_min: int = Field(ge=0)


class Fault(BaseModel):
    symptoms: list[str] = Field(min_length=1)
    causes: list[FaultCause] = Field(min_length=1)


class ToolFamily(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    prefix: str = Field(min_length=2, max_length=4, description="tool-ID prefix, e.g. LIT")
    area: tuple[float, float, float, float] = Field(description="x0, y0, x1, y1 in metres")
    pm_task: str
    faults: dict[str, Fault] = Field(min_length=1, description="fault code -> symptoms and root causes")


class Preset(BaseModel):
    label: str
    description: str
    family_mix: dict[str, float] = Field(description="share of jobs per tool family")
    constraint_engineer_share: float = Field(
        ge=0, le=1, description="engineers whose primary family is the constraint family"
    )
    down_share: float = Field(ge=0, le=1, description="unplanned tool-downs vs PMs")
    sla_critical: int = Field(gt=0, description="minutes allowed to start a bottleneck tool-down")
    sla_down: int = Field(gt=0)


class Shift(BaseModel):
    start_hour: int = Field(7, ge=0, le=23)
    length_min: int = Field(720, gt=0, le=24 * 60)


class Floor(BaseModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class FabProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str
    floor: Floor
    shift: Shift = Shift()
    walk_m_per_min: float = Field(60.0, gt=0)
    constraint_family: str = Field(description="the bottleneck tool family (e.g. lithography)")
    families: list[ToolFamily] = Field(min_length=1)
    presets: dict[str, Preset] = Field(min_length=1)

    @field_validator("families")
    @classmethod
    def _unique(cls, v: list[ToolFamily]) -> list[ToolFamily]:
        ids = [f.id for f in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate tool family ids")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> FabProfile:
        ids = {f.id for f in self.families}
        if self.constraint_family not in ids:
            raise ValueError(f"constraint_family {self.constraint_family!r} is not a tool family")
        for f in self.families:
            x0, y0, x1, y1 = f.area
            if not (0 <= x0 < x1 <= self.floor.width and 0 <= y0 < y1 <= self.floor.height):
                raise ValueError(f"area of {f.id} lies outside the {self.floor.width}x{self.floor.height} floor")
        for name, p in self.presets.items():
            unknown = set(p.family_mix) - ids
            if unknown:
                raise ValueError(f"preset {name} mixes unknown families {sorted(unknown)}")
        return self

    @property
    def family_ids(self) -> list[str]:
        return [f.id for f in self.families]

    def family(self, family_id: str) -> ToolFamily:
        return next(f for f in self.families if f.id == family_id)

    def public(self) -> dict:
        """What the UI needs (no fault catalogue)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "floor": self.floor.model_dump(),
            "shift": self.shift.model_dump(),
            "walk_m_per_min": self.walk_m_per_min,
            "constraint_family": self.constraint_family,
            "families": [{"id": f.id, "label": f.label, "prefix": f.prefix, "area": f.area} for f in self.families],
            "presets": {k: {"label": p.label, "description": p.description} for k, p in self.presets.items()},
        }


class UnknownFab(KeyError):
    pass


@lru_cache
def load_profiles(directory: str | None = None) -> dict[str, FabProfile]:
    root = Path(directory) if directory else PROFILES_DIR
    profiles = {}
    for path in sorted(root.glob("*.json")):
        profile = FabProfile.model_validate(json.loads(path.read_text()))
        if profile.id in profiles:
            raise ValueError(f"duplicate fab id {profile.id} in {path.name}")
        profiles[profile.id] = profile
    if not profiles:
        raise ValueError(f"no fab profiles found in {root}")
    return profiles


def get_profile(fab_id: str) -> FabProfile:
    from ..config import get_settings

    profiles = load_profiles(get_settings().profiles_dir)
    if fab_id not in profiles:
        raise UnknownFab(fab_id)
    return profiles[fab_id]


def all_profiles() -> dict[str, FabProfile]:
    from ..config import get_settings

    return load_profiles(get_settings().profiles_dir)
