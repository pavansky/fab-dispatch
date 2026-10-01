# Fab Maintenance Dispatch: a resource allocation engine

Assigns **equipment engineers** to **tool-downs and preventive maintenance (PM)** on a 300mm
semiconductor fab floor, using three allocation strategies, and compares them side by side in
a React UI.

- **Backend:** FastAPI, NumPy, SciPy (`linear_sum_assignment` for Hungarian)
- **Frontend:** React and Vite. The fab floor plan is drawn in plain SVG, so there are no map tiles or API keys.
- **Tests:** pytest (89 tests)

> Full write-up of the results: [docs/ANALYSIS.md](docs/ANALYSIS.md)

## Quick start

Requires Python 3.11+ and Node 20+.

```bash
# 1. Backend: http://127.0.0.1:8000  (OpenAPI docs at /docs)
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

```bash
# 2. Frontend: http://localhost:5173  (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

```bash
# 3. Tests and benchmark
cd backend
pytest -q
python -m scripts.benchmark --seeds 30
```

## Why this domain

Fab equipment maintenance is a natural fit for "mobile resources assigned to requests":

| Concept | In the fab |
|---|---|
| Resource | Equipment engineer with a home bay, a 12-hour shift (07:00–19:00), and certifications per tool family (litho, etch, deposition, CMP, implant, metrology) at level 1–3 |
| Request | A **tool-down** (unplanned, must be responded to within an SLA) or a **PM** (scheduled, wide window) on a specific tool |
| Priority | 3 = bottleneck tool down (litho scanners and other constraint tools), 2 = other tool down, 1 = PM |
| Location | Metres on the floor plan. Walking distance is **Manhattan**, because bays sit on a grid of aisles and you can't cut across tools |

## Data model (`backend/app/models.py`)

- `Engineer`: `x, y`, `skills {family: level}`, `shift_start/end`, `max_jobs`
- `Job`: `x, y`, `skill`, `min_level`, `priority`, `kind` (`down`/`pm`), `earliest`/`latest` **start** window, `duration`, `tool`
- `Assignment`: engineer, sequence in the route, arrival, start and end times, walking, cost breakdown, **explanation**, runner-up engineers, rejection counts
- `Unassigned`: job and a plain-language reason (for example "no engineer on shift holds litho level 3+")

Each engineer gets an **ordered route** (several jobs per shift), not a single job. This turns
the problem into a small vehicle-routing problem with time windows (VRPTW), which is what fab dispatch actually looks like.

## Constraints (`backend/app/planner.py`)

**Hard constraints** (never violated; the tests check every one):
1. The engineer is certified on the tool family
2. The engineer's certification level is at least the job's minimum
3. At most `max_jobs` per engineer
4. The engineer arrives before the window's latest start. Arriving early means waiting.
5. All work finishes before the end of the shift

**Soft constraints** (weighted cost, adjustable live in the UI):

| Term | Default | Why |
|---|---|---|
| Walking per 100 m | 4 | Time in transit is time not fixing tools |
| Idle wait per minute | 0.2 | An engineer standing at a tool waiting for its window is wasted capacity |
| Over-qualification per level | 8 | Don't send the only level-3 litho engineer to a level-1 job |
| Workload balance per job held | 5 | Spread load and avoid burning out one person |
| Priority reward per point | 60 | Serving a bottleneck down is worth far more than any walking cost |

All three algorithms share one engine. `best_insertion(engineer, job)` tries every position in
the engineer's current route, simulates the timing, and returns the cheapest feasible position
with its marginal cost (or the hard constraint that ruled it out). The algorithms differ only in
the **order and scope** of their decisions, so the comparison is fair.

## Algorithms (`backend/app/algorithms/`)

| Algorithm | Idea | Complexity |
|---|---|---|
| **Greedy** | Sort jobs by priority, then deadline (what a shift lead does by hand), and give each one the cheapest engineer. Choices are never revisited. | O(J·E·R) |
| **Hungarian in rounds** | Each round, build an engineers × open-jobs matrix of insertion costs and solve it optimally with Kuhn-Munkres. Each engineer gains at most one job per round, and rounds repeat until nothing feasible is left. | O(rounds·min(E,J)²·max(E,J)) |
| **Regret-2 insertion** (custom) | Each step, place the job with the largest gap between its best and second-best engineer. A job only one engineer can do goes first. This is built for scarce certifications such as litho. | O(J²·E·R), cached |

**Explanations:** every assignment records why it was made: dispatch order, Hungarian round,
or regret value; the runner-up engineer and its cost; how many engineers were rejected and why;
and a per-term cost breakdown. Unassigned jobs get a plain-language reason. Click any job in the UI to see these.

## UI

- **Floor plan:** tool-family areas, engineer home bays (squares), walking routes as L-shaped aisle paths, and jobs coloured by assigned engineer. Bottleneck downs are ringed; unassigned jobs are dashed red. Single or **side-by-side** view.
- **Algorithm comparison:** 11 metrics, with the best value per row highlighted
- **Decision explanation:** how each algorithm handled the selected job
- **Shift schedule:** a Gantt chart per engineer, showing idle waits
- **What-if:** change scenario preset, seed and size; drag weight sliders (re-solves live); click the floor to report a new tool-down; click an engineer to take them off shift

## Project layout

```
backend/
  app/models.py          domain model (pydantic)
  app/planner.py         route simulation, hard and soft constraints, insertion
  app/algorithms/        greedy.py, hungarian.py, regret.py
  app/engine.py          runs an algorithm, builds results and metrics
  app/generator.py       seeded synthetic fab: 4 presets
  app/main.py            FastAPI: /api/meta, /api/scenario, /api/allocate
  scripts/benchmark.py   multi-seed comparison
  tests/                 constraints, algorithm behaviour, API
frontend/src/            App.jsx and components/
docs/ANALYSIS.md         algorithm comparison write-up
```

## Assumptions

- Synthetic data only: the layout, SLAs and skill mix are illustrative, not from any real fab
- Static planning for one shift: every job is known up front (see the analysis for the online extension)
- Durations are deterministic, and each job needs one engineer
- Walking speed is 60 m/min in cleanroom garb; gowning happens once at shift start
