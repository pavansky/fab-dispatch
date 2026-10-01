# Contributing

## Set up

```bash
make setup            # Python venv + npm install
make dev              # API on :8000, UI on :5173 (demo sign-in, SQLite, no keys)
pip install pre-commit && pre-commit install   # format and lint on every commit
```

## Before you push

```bash
make check            # lint + format check + tests with coverage floor + audits + frontend build
```

CI runs the same checks, plus the suite on Python 3.11/3.12/3.14 and against Postgres.

## Conventions

- **Branches**: short-lived feature branches off `main`; merge by pull request.
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
  `docs:`, `ci:`, `refactor:`, `test:`, `chore:`. One logical change per commit.
- **Versions**: [SemVer](https://semver.org/). Breaking API changes bump the major version. Release
  notes go in `CHANGELOG.md` under the new version before tagging.
- **Database**: never edit a released migration. Add the next number in `backend/app/store.py`;
  keep it additive (see *Rollback* in [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md)).
- **Fab-specific behaviour** belongs in a fab profile, not in code. See
  [docs/ONBOARDING_A_FAB.md](docs/ONBOARDING_A_FAB.md).
- **Solver changes**: bump `ENGINE_VERSION` in `backend/app/cache.py` so cached plans from the old
  behaviour are never served, and re-run `python -m scripts.benchmark` to update
  `docs/ANALYSIS.md`.
- **Style**: ruff (format + lint) for Python, ESLint for the frontend. Module docstrings explain *why*.

## Releasing

See [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md): merge to `main` → verify in UAT → tag `vX.Y.Z`.
