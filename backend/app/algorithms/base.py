from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..models import Candidate
from ..planner import Insertion, describe_rejections


@dataclass
class Decision:
    """Why a job went to an engineer, recorded at the moment the choice was made."""

    tech_id: str
    cost: float
    breakdown: dict[str, float]
    explanation: str
    alternatives: list[Candidate] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)


def decision(chosen: Insertion, feasible: list[Insertion], rejected: Counter[str], why: str) -> Decision:
    others = [i for i in feasible if i.tech_id != chosen.tech_id][:3]
    runner_up = f"; next best {others[0].tech_id} at {others[0].cost:.1f}" if others else "; no other feasible engineer"
    text = f"{why} {chosen.tech_id} at cost {chosen.cost:.1f}{runner_up}. {describe_rejections(rejected).capitalize()}."
    return Decision(
        tech_id=chosen.tech_id,
        cost=round(chosen.cost, 2),
        breakdown=chosen.breakdown,
        explanation=text,
        alternatives=[Candidate(tech_id=i.tech_id, cost=round(i.cost, 2)) for i in others],
        rejections=dict(rejected),
    )
