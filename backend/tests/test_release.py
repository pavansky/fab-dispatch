"""One release version everywhere (the API, both package manifests and the changelog agree), and one
license: MIT, declared in both manifests, with every runtime dependency in the third-party notices."""

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


def test_mit_license_is_declared_everywhere():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License\n\nCopyright (c) ")
    assert tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["license"] == "MIT"
    assert json.loads((ROOT / "frontend/package.json").read_text())["license"] == "MIT"
    for dockerfile in ("backend/Dockerfile", "frontend/Dockerfile"):
        assert 'org.opencontainers.image.licenses="MIT"' in (ROOT / dockerfile).read_text()


def test_every_runtime_dependency_is_in_the_third_party_notices():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text().lower()
    python = [
        re.split(r"[=<>\[ ]", line)[0]
        for line in (ROOT / "backend/requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    node = list(json.loads((ROOT / "frontend/package.json").read_text())["dependencies"])
    missing = [name for name in python + node if name.lower() not in notices]
    assert not missing, f"add to THIRD_PARTY_NOTICES.md with its license: {missing}"
