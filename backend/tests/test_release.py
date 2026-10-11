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


def test_every_workflow_job_has_a_timeout_and_every_action_is_pinned_to_a_commit():
    """ENVIRONMENTS.md promises both: a hung job can't run for six hours, and a moved tag can't
    change what runs in CI or in a release."""
    import yaml

    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        for name, job in spec["jobs"].items():
            if "uses" in job:  # a reusable workflow: its own jobs carry the timeouts
                assert job["uses"].startswith("./.github/workflows/"), (path.name, name)
                continue
            assert "timeout-minutes" in job, f"{path.name}: job {name} has no timeout"
            for step in job["steps"]:
                if uses := step.get("uses"):
                    assert re.fullmatch(r"[\w.-]+/[\w.-]+(/[\w.-]+)*@[0-9a-f]{40}", uses), (
                        f"{path.name}: {uses} not pinned"
                    )
        # And a version comment next to every pin, so a human can read what it is.
        for line in path.read_text().splitlines():
            if "uses:" in line and "@" in line and "./.github" not in line:
                assert re.search(r"@[0-9a-f]{40} # v\d", line), f"{path.name}: {line.strip()}"


def test_the_release_gates_on_main_and_uat_before_publishing_anything():
    import yaml

    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
    assert "on-main" in jobs and "merge-base --is-ancestor" in jobs["on-main"]["steps"][-1]["run"]
    assert "on-main" in jobs["images"]["needs"] and jobs["verify"]["needs"] == "on-main"
    uat = jobs["uat"]["steps"][-1]["run"]
    assert "deployments?sha=$GITHUB_SHA" in uat and "workflows/smoke.yml/runs?head_sha=$GITHUB_SHA" in uat
    assert set(jobs["promote"]["needs"]) >= {"images", "uat", "verify", "on-main"}
    assert "EXPECTED_DATABASES" in (ROOT / ".github/workflows/smoke.yml").read_text()
