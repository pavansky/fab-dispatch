"""Seeded synthetic fab: a 400 m x 240 m floor split into tool-family areas.

The layout mirrors a typical 300mm fab: lithography in a central yellow-light bay,
with etch, deposition, CMP, implant and metrology areas around it. Tool IDs follow
the usual "family-bay-number" naming. All numbers are illustrative, not real fab data.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .knowledge import PM_TASKS, fault_symptom
from .models import SKILLS, Engineer, Job, Scenario, Settings

# x0, y0, x1, y1 in metres
AREAS: dict[str, tuple[float, float, float, float]] = {
    "litho": (150, 80, 250, 160),
    "etch": (20, 20, 140, 110),
    "deposition": (260, 20, 380, 110),
    "cmp": (20, 130, 140, 220),
    "implant": (260, 130, 380, 220),
    "metrology": (150, 20, 250, 70),
}
TOOL_PREFIX = {"litho": "LIT", "etch": "ETC", "deposition": "DEP", "cmp": "CMP", "implant": "IMP", "metrology": "MET"}
NAMES = ["Arun", "Mei", "Joon", "Priya", "Hsin", "Daniel", "Sofia", "Kenji", "Ravi", "Lina", "Tomas",
         "Yuna", "Imran", "Grace", "Wei", "Nadia", "Omar", "Ji-ho", "Anita", "Lukas", "Chen", "Fatima",
         "Hiro", "Sara", "Vikram", "Elena", "Min", "Kofi", "Ishaan", "Rosa"]


@dataclass(frozen=True)
class Preset:
    label: str
    description: str
    family_mix: dict[str, float]           # share of jobs per tool family
    litho_engineer_share: float            # share of engineers whose primary family is litho
    down_share: float                      # unplanned tool-downs vs PMs
    sla_critical: int                      # minutes allowed to start a bottleneck tool-down
    sla_down: int


PRESETS: dict[str, Preset] = {
    "normal": Preset("Normal shift", "Typical mix of PMs and tool-downs; staffing roughly matches load.",
                     {"litho": .15, "etch": .22, "deposition": .2, "cmp": .15, "implant": .1, "metrology": .18}, .18, .55, 45, 120),
    "litho_crunch": Preset("Litho crunch", "Scanner problems pile up while few engineers hold litho certifications.",
                           {"litho": .4, "etch": .15, "deposition": .15, "cmp": .1, "implant": .05, "metrology": .15}, .1, .7, 45, 120),
    "excursion": Preset("Excursion / surge", "Mostly unplanned downs with tight response targets.",
                        {"litho": .2, "etch": .25, "deposition": .2, "cmp": .1, "implant": .1, "metrology": .15}, .18, .9, 25, 60),
    "overstaffed": Preset("Overstaffed", "Plenty of engineers; the question is cost, not coverage.",
                          {"litho": .15, "etch": .22, "deposition": .2, "cmp": .15, "implant": .1, "metrology": .18}, .2, .5, 60, 150),
}


def _point_in(rng: random.Random, family: str) -> tuple[float, float]:
    x0, y0, x1, y1 = AREAS[family]
    return round(rng.uniform(x0 + 5, x1 - 5), 1), round(rng.uniform(y0 + 5, y1 - 5), 1)


def generate(seed: int = 7, n_engineers: int = 14, n_jobs: int = 45, preset: str = "normal") -> Scenario:
    cfg = PRESETS[preset]
    rng = random.Random(seed)
    families = list(cfg.family_mix)
    weights = list(cfg.family_mix.values())

    engineers = []
    n_litho = max(1, round(n_engineers * cfg.litho_engineer_share))
    others = [f for f in SKILLS if f != "litho"]
    for i in range(n_engineers):
        primary = "litho" if i < n_litho else others[(i - n_litho) % len(others)]
        skills = {primary: rng.choice([2, 3, 3] if primary == "litho" else [2, 2, 3])}
        for extra in rng.sample([f for f in SKILLS if f != primary], k=rng.choice([1, 1, 2])):
            # Cross-training onto litho is rare and shallow.
            skills[extra] = 1 if extra == "litho" else rng.choice([1, 2])
        x, y = _point_in(rng, primary)
        engineers.append(Engineer(
            id=f"E{i + 1:02d}", name=NAMES[i % len(NAMES)], x=x, y=y, skills=skills,
            shift_start=0, shift_end=720, max_jobs=rng.choice([4, 5, 5, 6]),
        ))

    jobs = []
    for i in range(n_jobs):
        fam = rng.choices(families, weights)[0]
        x, y = _point_in(rng, fam)
        tool = f"{TOOL_PREFIX[fam]}-{rng.randint(1, 4):02d}{rng.choice('ABCD')}"
        if rng.random() < cfg.down_share:
            # Litho scanners and anything flagged as a bottleneck get the tightest SLA.
            critical = fam == "litho" or rng.random() < 0.25
            earliest = rng.randint(0, 600)
            priority = 3 if critical else 2
            latest = earliest + (cfg.sla_critical if critical else cfg.sla_down)
            # The planner's duration is the standard estimate for the fault code; the
            # repair history (knowledge.py) can predict a better one from the symptom.
            _, symptom, duration = fault_symptom(rng, fam)
            kind = "down"
        else:
            earliest = rng.randint(0, 420)
            priority, latest, duration, kind = 1, earliest + 240, rng.choice([90, 120, 180, 240]), "pm"
            symptom = PM_TASKS[fam]
        min_level = rng.choice([2, 2, 3]) if fam == "litho" else rng.choice([1, 1, 2])
        jobs.append(Job(id=f"J{i + 1:03d}", x=x, y=y, skill=fam, min_level=min_level, priority=priority,
                        kind=kind, earliest=earliest, latest=latest, duration=duration, tool=tool,
                        symptom=symptom))
    return Scenario(engineers=engineers, jobs=jobs, settings=Settings())
