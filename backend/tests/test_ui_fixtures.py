"""Contract between the API and the UI's test fixtures.

The frontend component tests render against JSON captured from this API
(``scripts/export_ui_fixtures.py``). If a response changes shape (a field added, renamed
or removed), the UI tests would keep passing against stale data. This test catches that.

"Shape" is more than key sets and type names: enum-like strings (algorithm names, event kinds,
roles, presets, ...) and small integer codes (priority, certification level) are compared by
value, and a list that has items in the committed fixture must still have items from the API.
"""

import json

import pytest

from scripts.export_ui_fixtures import META_NOTE, OUT, export

# Fields whose values are identifiers from a fixed vocabulary, not data: a renamed algorithm,
# a new event kind or a changed role would otherwise pass as "still a string". Deployment
# facts that legitimately differ between the export machine and CI (``store`` is "postgres" in
# the Postgres job, ``auth_mode`` and ``vector_index`` follow the environment) are type-only.
ENUM_FIELDS = {
    "algorithm",
    "family",
    "intent",
    "kind",
    "mode",
    "preset",
    "role",
    "section",
    "speed",
    "status",
    "verdict",
    "priority",
    "min_level",
    "level",
}


def shape(value, key=None):
    """Structure without data: dict keys (recursively), list element shape plus whether the list has
    items, scalar type, and the value itself for enum-like fields."""
    if isinstance(value, dict):
        return {k: shape(v, k) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return ["non-empty", shape(value[0], key)] if value else ["empty"]
    if isinstance(value, bool) or value is None:
        return type(value).__name__
    if key in ENUM_FIELDS and isinstance(value, str | int):
        return ("enum", value)
    if isinstance(value, int | float):
        return "number"
    return type(value).__name__


def committed_names() -> list[str]:
    return sorted(p.stem for p in OUT.glob("*.json") if not p.name.startswith("_"))


@pytest.fixture(scope="module")
def fresh():
    return export()


@pytest.mark.parametrize("name", committed_names())
def test_ui_fixtures_match_the_api(fresh, name):
    assert name in fresh, f"{name}.json is committed but no longer exported"
    committed = json.loads((OUT / f"{name}.json").read_text())
    assert shape(committed) == shape(fresh[name]), (
        f"frontend fixture {name}.json no longer matches the API. "
        "Refresh with: cd backend && python -m scripts.export_ui_fixtures"
    )


def test_every_exported_fixture_is_committed(fresh):
    assert sorted(fresh) == committed_names()


def test_fixtures_cover_assigned_and_unassigned_work(fresh):
    plans = fresh["plans"]
    assert all(p["assignments"] for p in plans.values())
    assert all(p["unassigned"] for p in plans.values())


def test_shape_compares_enums_and_list_emptiness():
    assert shape({"algorithm": "alns"}) != shape({"algorithm": "pyvrp"})
    assert shape({"events": [{"kind": "job_reported"}]}) != shape({"events": []})
    assert shape({"events": [{"kind": "job_reported"}]}) != shape({"events": [{"kind": "replanned"}]})
    assert shape({"name": "Mei", "x": 1}) == shape({"name": "Joon", "x": 2.5})


def test_export_note_says_budgets_are_reduced_and_timings_are_the_export_machines():
    note = json.loads((OUT / META_NOTE).read_text())
    assert "runtime_ms" in note["note"] and "export machine" in note["note"]
    assert note["export_budgets"]["alns_iterations"] < note["shipped_budgets"]["alns_iterations"]
    assert note["export_budgets"]["pyvrp_iterations"] < note["shipped_budgets"]["pyvrp_iterations"]
    assert note["machine"]["platform"]
