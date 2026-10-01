# Fab Dispatch: a resource allocation engine

Assigns **equipment engineers** to **tool-downs and preventive maintenance** on a 300mm semiconductor
fab floor. Five allocation strategies, from a one-pass greedy to the state-of-the-art PyVRP solver, are
compared side by side. A **live dispatch** mode re-plans in real time as tool-downs arrive, and a
**repair-history** index (Qdrant) predicts how long a fault will take from similar past repairs.

Runs entirely on a laptop with no accounts or API keys. The same code runs in production on Vercel with
Supabase Postgres ([fab-dispatch.vercel.app](https://fab-dispatch.vercel.app)), and can use an optional Qdrant server.

| | |
|---|---|
| **Backend** | FastAPI · NumPy · SciPy (Hungarian, HiGHS MILP) · PyVRP · Qdrant client · psycopg 3 |
| **Frontend** | React 19 · Vite · SVG floor plan (no map tiles, no keys) |
| **Storage** | SQLite locally (zero setup) · Postgres / Supabase in production |
| **Tests** | 136 pytest (constraints, optimality, API contract, store on SQLite *and* Postgres) · 7 vitest |
| **Docs** | [Analysis](docs/ANALYSIS.md) · [Architecture](docs/ARCHITECTURE.md) · [Decisions](docs/DECISIONS.md) · [Deployment](docs/DEPLOYMENT.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md) |

---

## Quick start (local, no keys)

Requires **Python 3.12+** and **Node 20+**.

```bash
# 1. API on http://127.0.0.1:8000 (OpenAPI docs at /docs)
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

```bash
# 2. UI on http://localhost:5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Or, with `make`: `make setup` once, then `make dev`.

```bash
# Tests and benchmark
cd backend && pip install -r requirements-dev.txt && pytest -q
cd frontend && npm test
cd backend && python -m scripts.benchmark --seeds 20
```

**Production-like stack** (Postgres + Qdrant server + API + nginx): `docker compose up --build`, then
http://localhost:8080.

---

## The problem, in fab terms

| Concept | In this model |
|---|---|
| **Resource** | Equipment engineer: home bay on the floor, 12-hour shift (07:00–19:00), max jobs per shift, certified per tool family (litho, etch, deposition, CMP, implant, metrology) at level 1–3 |
| **Request** | A **tool-down** (unplanned, must be started within an SLA) or a **PM** (scheduled, wide window) on a specific tool, with a free-text symptom |
| **Priority** | 3 = bottleneck tool down (litho scanners, constraint tools) · 2 = other tool down · 1 = PM |
| **Distance** | Metres on the floor plan, **Manhattan**: bays sit on a grid of aisles and you can't walk through tools |
| **Assignment** | An ordered **route** of jobs per engineer, not one job each. This makes it a technician routing and scheduling problem (VRPTW with skills) |

**Hard constraints** (never violated, checked by tests on every strategy): certification, level, max
jobs, start-time window, shift end.

**Soft constraints** (one weighted cost, adjustable live in the UI): walking, idle wait, over-qualification
(don't send the only level-3 litho engineer to a level-1 job), workload balance, priority reward for
served work, and in live mode a stability penalty for moving a job to a different engineer.

## Five strategies

| Strategy | Kind | Idea | Typical solve |
|---|---|---|---|
| **Greedy** | constructive | priority → deadline order, cheapest feasible engineer, never revisits | ~1 ms |
| **Hungarian** | assignment | optimal engineer × job matching per round (Kuhn-Munkres), repeated | ~3 ms |
| **Regret-2** | constructive | place the job with most to lose first; protects scarce certifications | ~7 ms |
| **ALNS** | metaheuristic | destroy/repair search on the *exact* objective (Ropke & Pisinger; Kovacs et al. for technician routing) | ~0.17 s |
| **PyVRP** | metaheuristic | state-of-the-art iterated local search (C++ core), warm-started from regret | ~0.4 s |

There's also an **exact solver** (route enumeration + set-partitioning MILP on HiGHS) for small shifts,
used to measure each heuristic's **true optimality gap**. Every strategy shares one constraint engine
and one cost function, so they differ only in how they decide.

**Headline results** (80 seeded shifts; full tables in [docs/ANALYSIS.md](docs/ANALYSIS.md)):
- PyVRP has the cheapest plan in 78/80 shifts: 23–30% cheaper than the best one-pass method in three of
  four scenario types, mostly by cutting idle wait.
- Against a proven optimum on small shifts, ALNS is closest (0.9% mean gap) because it optimises the
  exact objective; PyVRP is 1.8%; greedy is 10.5%.
- Hungarian responds fastest to tool-downs and balances load best, but builds up the most idle time.
- When certifications run out (litho crunch), every strategy hits the same ceiling. That's a staffing
  problem, and the Workforce view says so.

## What's in the UI

- **Overview**: a recommended plan for the chosen goal (protect bottleneck tools / maximise coverage /
  lowest cost) with the honest trade-off, scorecards against greedy, generated findings, and the jobs
  where the strategies disagree.
- **Floor plan**: routes along aisles, hover any job to focus its engineer's route with stop numbers,
  coverage changes against greedy, side-by-side view of all five.
- **Inspector**: why each strategy did what it did (runner-up engineer, rejection reasons, cost
  breakdown), plus **repair history**: predicted duration with p10–p90, likely root cause, who has fixed
  it before.
- **Schedule**: Gantt per engineer with walking and idle wait.
- **Workforce**: demand against certified supply per tool family, and a certification matrix. Shows when
  the problem is staffing rather than the algorithm.
- **Live dispatch**: the shift runs in real time. Started work is locked, tool-downs appear when reported,
  every event triggers a re-plan, and **every open dashboard updates over SSE**. Share the link to
  watch from another device.
- **Benchmark**: all strategies over many seeded shifts, plus a measured optimality gap.
- What-ifs: drag cost weights (re-solves live), report a job by clicking the floor, take an engineer off
  shift, plan with history-predicted durations. Light and dark themes.

## Production features

- **Deterministic solvers** (fixed seeds, iteration budgets, time only as a safety cap). The same input
  always gives the same plan, which makes caching safe. Budgets sit at the knee of the measured
  quality-vs-iterations curve (ANALYSIS, "Sizing the search budget").
- **Best-value recommendations**: never trade away bottleneck coverage; treat cost differences inside a
  noise margin as ties and pick the fastest; benchmark verdicts use paired bootstrap 95% CIs.
- **Two-tier content-addressed plan cache**: an in-process LRU, then a database table shared across
  instances. In production a repeated plan is served in under 1 ms of server time. The browser keeps its
  own cache too, and cancels stale requests.
- **Progressive results**: all five strategies are requested in parallel and each renders as it lands.
- **Live shifts**: server-owned state with optimistic versioning (`If-Match` → 409), an append-only event
  log, and SSE that resumes with `Last-Event-ID` and works across instances and on serverless.
- **HTTP**: ETag/304 on reads, gzip, one JSON error envelope with request IDs, per-client rate limits on
  expensive endpoints, security headers, `/api/livez` and `/api/health`.
- **Ops**: typed settings from env (`FAB_*`, see [.env.example](.env.example)), structured JSON logs,
  Docker images (non-root, healthchecks), compose stack, and CI covering lint, tests on SQLite *and*
  Postgres, frontend tests and build, and image builds.

## Project layout

```
backend/
  app/
    models.py            domain model (pydantic)
    planner.py           route simulation, hard/soft constraints, insertion, live freezing
    algorithms/          greedy · hungarian · regret · alns · pyvrp_ils · exact
    engine.py            run a strategy -> assignments, explanations, metrics
    live.py              rolling-horizon live dispatch
    knowledge.py         repair history + Qdrant index + duration prediction
    services.py cache.py store.py   plan cache, SQLite/Postgres repository
    routes/              system · planning · live (SSE) · repairs
    config.py observability.py deps.py http.py main.py
  scripts/benchmark.py   produces the tables in docs/ANALYSIS.md
  tests/
frontend/src/
  App.jsx  api.js  lib/ (analysis, metrics, usePlans)  components/
docs/                    ANALYSIS · ARCHITECTURE · DECISIONS · DEPLOYMENT
vercel.json  docker-compose.yml  Makefile  .github/workflows/ci.yml  .env.example
```

## Assumptions

- Synthetic data: the floor layout, SLAs, skill mix and repair history are illustrative, not from any
  real fab. The generator is seeded, so every scenario is reproducible.
- One engineer per job. Walking speed is 60 m/min in cleanroom garb, and gowning happens once at shift start.
- In live mode an engineer already walking to a job they haven't started can be redirected.
