"""Seeded synthetic shifts for any fab profile.

Everything site-specific (floor plan, tool families, tool-ID prefixes, fault catalogue,
shift length, presets) comes from the fab profile; this module only holds the generic
rules for staffing and work mix. The same seed and profile always give the same shift,
so benchmarks are reproducible. All numbers are illustrative, not real fab data.
"""

from __future__ import annotations

import random

from .config import get_settings
from .fabs import FabProfile, get_profile
from .knowledge import fault_symptom
from .models import Engineer, Job, Scenario, Settings

NAMES = [
    "Arun",
    "Mei",
    "Joon",
    "Priya",
    "Hsin",
    "Daniel",
    "Sofia",
    "Kenji",
    "Ravi",
    "Lina",
    "Tomas",
    "Yuna",
    "Imran",
    "Grace",
    "Wei",
    "Nadia",
    "Omar",
    "Ji-ho",
    "Anita",
    "Lukas",
    "Chen",
    "Fatima",
    "Hiro",
    "Sara",
    "Vikram",
    "Elena",
    "Min",
    "Kofi",
    "Ishaan",
    "Rosa",
]


def _point_in(rng: random.Random, profile: FabProfile, family: str) -> tuple[float, float]:
    x0, y0, x1, y1 = profile.family(family).area
    return round(rng.uniform(x0 + 5, x1 - 5), 1), round(rng.uniform(y0 + 5, y1 - 5), 1)


def generate(
    seed: int = 7, n_engineers: int = 14, n_jobs: int = 45, preset: str = "normal", fab_id: str | None = None
) -> Scenario:
    profile = get_profile(fab_id or get_settings().default_fab)
    cfg = profile.presets[preset]
    rng = random.Random(seed)
    families = list(cfg.family_mix)
    weights = list(cfg.family_mix.values())
    constraint = profile.constraint_family
    all_families = profile.family_ids
    shift_len = profile.shift.length_min

    engineers = []
    n_constraint = max(1, round(n_engineers * cfg.constraint_engineer_share))
    others = [f for f in all_families if f != constraint]
    for i in range(n_engineers):
        primary = constraint if i < n_constraint else others[(i - n_constraint) % len(others)]
        skills = {primary: rng.choice([2, 3, 3] if primary == constraint else [2, 2, 3])}
        for extra in rng.sample([f for f in all_families if f != primary], k=rng.choice([1, 1, 2])):
            # Cross-training onto the constraint family is rare and shallow.
            skills[extra] = 1 if extra == constraint else rng.choice([1, 2])
        x, y = _point_in(rng, profile, primary)
        engineers.append(
            Engineer(
                id=f"E{i + 1:02d}",
                name=NAMES[i % len(NAMES)],
                x=x,
                y=y,
                skills=skills,
                shift_start=0,
                shift_end=shift_len,
                max_jobs=rng.choice([4, 5, 5, 6]),
            )
        )

    jobs = []
    for i in range(n_jobs):
        fam = rng.choices(families, weights)[0]
        x, y = _point_in(rng, profile, fam)
        tool = f"{profile.family(fam).prefix}-{rng.randint(1, 4):02d}{rng.choice('ABCD')}"
        if rng.random() < cfg.down_share:
            # The constraint family and anything flagged as a bottleneck get the tightest SLA.
            critical = fam == constraint or rng.random() < 0.25
            earliest = rng.randint(0, max(0, shift_len - 120))
            priority = 3 if critical else 2
            latest = earliest + (cfg.sla_critical if critical else cfg.sla_down)
            # The planner's duration is the standard estimate for the fault code; the
            # repair history (knowledge.py) adds a P10-P90 range from similar past repairs
            # (scripts/duration_study.py measures both).
            _, symptom, duration = fault_symptom(rng, profile, fam)
            kind = "down"
        else:
            earliest = rng.randint(0, max(0, shift_len - 300))
            priority, latest, duration, kind = 1, earliest + 240, rng.choice([90, 120, 180, 240]), "pm"
            symptom = profile.family(fam).pm_task
        min_level = rng.choice([2, 2, 3]) if fam == constraint else rng.choice([1, 1, 2])
        jobs.append(
            Job(
                id=f"J{i + 1:03d}",
                x=x,
                y=y,
                skill=fam,
                min_level=min_level,
                priority=priority,
                kind=kind,
                earliest=earliest,
                latest=latest,
                duration=duration,
                tool=tool,
                symptom=symptom,
            )
        )
    return Scenario(
        fab_id=profile.id,
        engineers=engineers,
        jobs=jobs,
        settings=Settings(
            walk_m_per_min=profile.walk_m_per_min, floor_width=profile.floor.width, floor_height=profile.floor.height
        ),
    )
