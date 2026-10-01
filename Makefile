# Common tasks. Everything also works without make: see README.
PY := backend/.venv/bin/python

.PHONY: setup dev api web test lint format cov audit check bench gap up down clean

setup:            ## create the Python venv and install both apps
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install

api:              ## FastAPI on :8000 with auto-reload
	cd backend && .venv/bin/uvicorn app.main:app --port 8000 --reload --reload-dir app

web:              ## Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

dev:              ## API and UI together (Ctrl-C stops both)
	$(MAKE) -j2 api web

test:             ## backend + frontend tests
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

lint:             ## ruff + format check + eslint (what CI runs)
	cd backend && .venv/bin/ruff check app tests scripts && .venv/bin/ruff format --check app tests scripts
	cd frontend && npm run lint

format:           ## auto-fix formatting and safe lint issues
	cd backend && .venv/bin/ruff format app tests scripts && .venv/bin/ruff check --fix app tests scripts

cov:              ## backend tests with the CI coverage floor
	cd backend && .venv/bin/pytest -q --cov=app --cov-fail-under=85

audit:            ## known-vulnerability scan of both dependency trees
	cd backend && .venv/bin/pip-audit -r requirements.txt --progress-spinner off
	cd frontend && npm audit --audit-level=high

check: lint cov audit   ## everything CI checks, locally, before you push
	cd frontend && npm test && npm run build

bench:            ## regenerate the comparison tables in docs/ANALYSIS.md
	cd backend && .venv/bin/python -m scripts.benchmark --seeds 20

up:               ## production-like stack: Postgres + Qdrant + API + nginx on :8080
	docker compose up --build -d

down:
	docker compose down

clean:
	rm -rf backend/data frontend/dist
