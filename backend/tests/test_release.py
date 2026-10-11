"""One release version everywhere (the API, both package manifests and the changelog agree), one
license: MIT, declared in both manifests, with every runtime and development dependency in the
third-party notices, and README numbers that match what the test suites actually contain."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_is_the_same_everywhere():
    pyproject = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    package = json.loads((ROOT / "frontend/package.json").read_text())["version"]
    # An "## [Unreleased]" section may sit above the newest release; the first x.y.z heading counts.
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


def _requirements(name: str) -> list[str]:
    return [
        re.split(r"[=<>\[ ]", line)[0]
        for line in (ROOT / "backend" / name).read_text().splitlines()
        if line and not line.startswith(("#", "-r "))
    ]


def _is_listed(name: str, notices: str) -> bool:
    """The package name as a link text, a backticked token or a table cell, never as a word in prose
    ("react" inside a sentence must not count for react-dom or react-markdown)."""
    token = re.escape(name)
    return re.search(rf"\[{token}\]\(|`{token}`|\|\s*{token}\s*\|", notices, re.I) is not None


def test_every_dependency_is_in_the_third_party_notices():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    python = _requirements("requirements.txt") + _requirements("requirements-dev.txt")
    node = list(json.loads((ROOT / "frontend/package.json").read_text())["dependencies"])
    missing = [name for name in python + node if not _is_listed(name, notices)]
    assert not missing, f"add to THIRD_PARTY_NOTICES.md with its license, as a [link] or `token`: {missing}"


def test_notice_matching_needs_a_token_not_a_substring():
    assert _is_listed("react", "| [react](https://x) | UI | MIT |")
    assert _is_listed("highspy", "with `highspy` (MIT)")
    assert not _is_listed("react", "| [react-dom](https://x) | UI | MIT |")
    assert not _is_listed("react", "the UI reacts to every event")


def count_backend_tests() -> int:
    """Every collected backend test, the slow ones included (``addopts`` deselects them by default)."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "tests"],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(re.search(r"^(\d+) tests? collected", out, re.M).group(1))


def count_frontend_tests() -> int:
    files = list((ROOT / "frontend/src").rglob("*.test.js")) + list((ROOT / "frontend/src").rglob("*.test.jsx"))
    return sum(len(re.findall(r"^\s*(?:it|test)\(", f.read_text(), re.M)) for f in files)


def count_e2e_tests() -> int:
    return sum(len(re.findall(r"^\s*test\(", f.read_text(), re.M)) for f in (ROOT / "frontend/e2e").glob("*.spec.js"))


@pytest.mark.skipif(not (ROOT / "frontend/e2e").is_dir(), reason="frontend not checked out")
def test_readme_test_counts_match_the_suites():
    """The counts in README.md and docs/reviewers.md are checked, not maintained by hand: when a
    test is added, this fails with the numbers to write."""
    backend, frontend, e2e = count_backend_tests(), count_frontend_tests(), count_e2e_tests()
    total = backend + frontend + e2e
    readme = (ROOT / "README.md").read_text()
    reviewers = (ROOT / "docs/reviewers.md").read_text()
    expected = {
        "README badge": (readme, f"/badge/tests-{total}-"),
        "README highlights": (readme, f"{backend} backend tests, {frontend} frontend component tests"),
        "README highlights (e2e)": (readme, f"and {e2e} Playwright end-to-end tests"),
        "README testing table (backend)": (readme, f"| Backend | pytest | **{backend}**"),
        "README testing table (frontend)": (readme, f"| Frontend components | Vitest + Testing Library | **{frontend}**"),
        "README testing table (e2e)": (readme, f"| End-to-end | Playwright | **{e2e}**"),
        "README project structure": (readme, f"tests/                   {backend} tests"),
        "docs/reviewers.md": (reviewers, f"**{total}** automated tests"),
    }
    stale = [where for where, (text, needle) in expected.items() if needle not in text]
    assert not stale, (
        f"test counts are stale in {stale}: backend {backend}, frontend {frontend}, e2e {e2e}, total {total}"
    )
