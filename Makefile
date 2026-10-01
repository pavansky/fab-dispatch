# Common tasks. Everything also works without make: see README.
PY := backend/.venv/bin/python

.PHONY: setup dev api web test lint bench gap up down clean

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

lint:
	cd backend && .venv/bin/ruff check app tests scripts

bench:            ## regenerate the comparison tables in docs/ANALYSIS.md
	cd backend && .venv/bin/python -m scripts.benchmark --seeds 20

up:               ## production-like stack: Postgres + Qdrant + API + nginx on :8080
	docker compose up --build -d

down:
	docker compose down

clean:
	rm -rf backend/data frontend/dist
