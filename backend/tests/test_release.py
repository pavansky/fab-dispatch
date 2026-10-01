"""One release version everywhere: the API, both package manifests and the changelog agree."""

import json
import re
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_is_the_same_everywhere():
    pyproject = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    package = json.loads((ROOT / "frontend/package.json").read_text())["version"]
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
    assert APP_VERSION == pyproject == package == newest


def test_health_and_meta_report_the_release_and_commit():
    health = TestClient(app).get("/api/health").json()
    assert health["release"] == APP_VERSION and health["commit"]
