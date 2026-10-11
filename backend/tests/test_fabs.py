"""Fab profiles: Fab 1 is reproducible bit-for-bit, and any valid profile just works."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import allocate
from app.fabs import FabProfile, all_profiles, load_profiles
from app.generator import generate
from app.main import app
from app.models import Weights
from tests.conftest import auth_headers

GOLDEN = json.loads((Path(__file__).parent / "golden" / "fab1_scenarios.json").read_text())


@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_fab1_profile_reproduces_the_original_generator(key):
    preset, seed = key.rsplit("-", 1)
    data = generate(int(seed), 14, 45, preset, "fab1-300mm-logic").model_dump(mode="json")
    data.pop("fab_id")
    assert hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() == GOLDEN[key]


def test_each_fab_uses_its_own_families_floor_and_shift():
    for p in all_profiles().values():
        sc = generate(1, 10, 30, next(iter(p.presets)), p.id)
        assert sc.fab_id == p.id
        assert {j.skill for j in sc.jobs} <= set(p.family_ids)
        assert all(e.shift_end == p.shift.length_min for e in sc.engineers)
        assert sc.settings.floor_width == p.floor.width
        res = allocate(sc, Weights(), "regret")
        assert res.metrics["assigned"] > 0


def test_cross_training_on_the_constraint_family_is_usable():
    """Engineers cross-trained onto the constraint family are level 1: enough for some of
    its PMs, never for a tool-down on a constraint tool."""
    for p in all_profiles().values():
        c = p.constraint_family
        shifts = [generate(seed, 14, 45, preset, p.id) for preset in p.presets for seed in range(3)]
        jobs = [j for sc in shifts for j in sc.jobs if j.skill == c]
        assert all(j.min_level >= 2 for j in jobs if j.kind == "down")
        assert any(j.min_level == 1 for j in jobs if j.kind == "pm")
        assert any(e.skills.get(c) == 1 for sc in shifts for e in sc.engineers)


def test_priority_3_means_a_tool_down_on_the_constraint_family():
    """The glossary's definition: priority 3 is a tool-down on the bottleneck family, nothing
    else; other tool-downs are priority 2 and PMs are priority 1."""
    for p in all_profiles().values():
        c = p.constraint_family
        for preset in p.presets:
            for seed in range(3):
                for j in generate(seed, 14, 45, preset, p.id).jobs:
                    expected = 1 if j.kind == "pm" else (3 if j.skill == c else 2)
                    assert j.priority == expected, (p.id, preset, seed, j.id)


def test_overstaffed_preset_really_adds_certified_engineers():
    """Overstaffed must mean more bottleneck-certified engineers than a normal shift at the same
    headcount (and never fewer skills), not only wider response windows. It is kept to one extra
    certified engineer because every one multiplies the routes the exact proof enumerates."""
    for p in all_profiles().values():
        c = p.constraint_family
        for seed in range(3):
            normal = generate(seed, 14, 45, "normal", p.id).engineers
            over = generate(seed, 14, 45, "overstaffed", p.id).engineers
            certified = lambda engs: sum(1 for e in engs if e.skills.get(c, 0) >= 2)
            assert certified(over) >= certified(normal) + 1 and certified(over) >= 4, (p.id, seed)
            assert sum(len(e.skills) for e in over) >= sum(len(e.skills) for e in normal), (p.id, seed)


def test_profile_rejects_impossible_cross_training(fab1):
    raw = fab1.model_dump()
    raw["presets"]["normal"]["cross_training"] = [len(fab1.families)]
    with pytest.raises(ValueError, match="cross_training"):
        FabProfile.model_validate(raw)


def test_api_lists_fabs_and_plans_for_fab2():
    client = TestClient(app, headers=auth_headers("dispatcher"))
    ids = [f["id"] for f in client.get("/api/fabs").json()]
    assert ids == sorted(ids) and {"fab1-300mm-logic", "fab2-200mm-analog"} <= set(ids)
    fab2 = client.get("/api/fabs/fab2-200mm-analog").json()
    assert fab2["constraint_family"] == "photo" and fab2["shift"]["length_min"] == 480
    sc = client.post(
        "/api/scenario", json={"fab_id": "fab2-200mm-analog", "preset": "photo_crunch", "n_jobs": 20}
    ).json()
    assert client.post("/api/plan", json={"scenario": sc, "algorithm": "pyvrp"}).status_code == 200
    # A Fab 1 tool family smuggled into a Fab 2 scenario is rejected.
    sc["jobs"][0]["skill"] = "litho"
    r = client.post("/api/plan", json={"scenario": sc, "algorithm": "greedy"})
    assert r.status_code == 422 and "not defined" in r.json()["error"]["message"]


def test_invalid_profiles_fail_fast(tmp_path):
    base = json.loads((Path(__file__).parents[1] / "app/fabs/profiles/fab2-200mm-analog.json").read_text())
    bad = dict(base, constraint_family="nope")
    with pytest.raises(ValueError, match="constraint_family"):
        FabProfile.model_validate(bad)
    off_floor = json.loads(json.dumps(base))
    off_floor["families"][0]["area"] = [0, 0, 999, 10]
    with pytest.raises(ValueError, match="outside"):
        FabProfile.model_validate(off_floor)
    (tmp_path / "x.json").write_text(json.dumps(base))
    assert list(load_profiles(str(tmp_path))) == ["fab2-200mm-analog"]
