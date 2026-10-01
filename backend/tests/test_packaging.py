"""Vercel installs from pyproject.toml; reviewers install from requirements.txt. Keep them identical."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_and_requirements_pin_the_same_packages():
    reqs = {line.split("#")[0].strip() for line in (ROOT / "requirements.txt").read_text().splitlines()}
    reqs.discard("")
    deps = set(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"])
    assert deps == reqs
