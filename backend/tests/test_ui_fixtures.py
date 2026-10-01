"""Contract between the API and the UI's test fixtures.

The frontend component tests render against JSON captured from this API
(``scripts/export_ui_fixtures.py``). If a response changes shape (a field added, renamed
or removed), the UI tests would keep passing against stale data. This test catches that.
"""

import json

import pytest

from scripts.export_ui_fixtures import OUT, export


def shape(value):
    """Structure without values: dict keys (recursively), list element shape, scalar type."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if isinstance(value, bool) or value is None:
        return type(value).__name__
    if isinstance(value, int | float):
        return "number"
    return type(value).__name__


@pytest.fixture(scope="module")
def fresh():
    return export()


@pytest.mark.parametrize("name", sorted(p.stem for p in OUT.glob("*.json")))
def test_ui_fixtures_match_the_api(fresh, name):
    assert name in fresh, f"{name}.json is committed but no longer exported"
    committed = json.loads((OUT / f"{name}.json").read_text())
    assert shape(committed) == shape(fresh[name]), (
        f"frontend fixture {name}.json no longer matches the API. "
        "Refresh with: cd backend && python -m scripts.export_ui_fixtures"
    )


def test_every_exported_fixture_is_committed(fresh):
    assert sorted(fresh) == sorted(p.stem for p in OUT.glob("*.json"))


def test_fixtures_cover_assigned_and_unassigned_work(fresh):
    plans = fresh["plans"]
    assert all(p["assignments"] for p in plans.values())
    assert all(p["unassigned"] for p in plans.values())
