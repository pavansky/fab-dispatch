## What and why

## How it was tested
- [ ] `make test` passes (backend + frontend)
- [ ] `make lint` passes
- [ ] Tried it locally / on the PR preview

## Checklist
- [ ] Database change? Added a **new** migration in `backend/app/store.py` (never edit a released one)
- [ ] New fab or profile change? Profile validates (`pytest tests/test_fabs.py`)
- [ ] User-visible change? Added a line to `CHANGELOG.md` under *Unreleased*
- [ ] Docs updated where behaviour changed
