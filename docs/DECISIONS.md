# Decision log

Short records of the choices that shape this system: context, decision, and what we gave up.

---

### D1. Model routes, not one-to-one assignments
**Context.** The brief allows a simple resource ↔ request pairing. A fab engineer handles 4–6 jobs a
shift, and the order decides whether later windows are reachable.
**Decision.** Each engineer gets an ordered route, so this is a VRPTW with skills (technician routing
and scheduling).
**Trade-off.** Harder than bipartite matching. It's also why Hungarian has to run in rounds, which turned
out to be one of the more interesting findings.

### D2. One constraint engine shared by every strategy
**Decision.** All feasibility and cost logic lives in `planner.py`. External solvers (PyVRP) are
replayed through it.
**Why.** Comparisons are only fair if every strategy is scored by identical rules. It also means
hard-constraint tests cover all strategies at once.

### D3. Manhattan distance on a floor plan, SVG instead of a map
**Decision.** Positions are metres on a 400 × 240 m fab floor, and walking is Manhattan distance along
aisles. Rendered as SVG.
**Why.** That's how people move in a fab, and it needs no map tiles or keys. The brief explicitly allows
SVG.

### D4. Which advanced algorithms
**Context.** Literature review: ALNS (Ropke & Pisinger 2006; Kovacs et al. 2012, applied to technician
routing with skill levels) and HGS/ILS (Vidal; PyVRP) dominate. On the published VRPTW benchmarks,
PyVRP reaches about 0.2–0.8% gaps against about 10% for OR-Tools.
**Decision.** Add **PyVRP** (best quality per second, 1.2 MB wheel, MIT), a hand-written **ALNS** (optimises
our exact objective including balance), and an **exact MILP** baseline (SciPy/HiGHS, no extra dependency).
**Rejected.** OR-Tools routing: heavier install (pandas, protobuf), slower cold starts on serverless, and
weaker than PyVRP at short time limits. VROOM: its lexicographic objective can't express our weights.

### D5. Deterministic solvers
**Decision.** Seeds are fixed. Search stops on an iteration budget, and time is only a safety cap.
**Why.** Users shouldn't see plans change on refresh, and determinism makes content-addressed caching
valid. Results that hit the time cap aren't shared across instances.

### D6. Two-tier plan cache keyed by content
**Decision.** SHA-256 of the canonical input plus `ENGINE_VERSION`. An in-process LRU first, then a
`plan_cache` table.
**Why.** Slider back-and-forth and multiple viewers are the common case. A database tier means a cold
serverless instance still benefits. Bumping the version invalidates everything without a migration.

### D7. SQLite locally, Postgres in production, behind one `Store`
**Context.** The brief requires running locally with no keys. Production needs durable shared state.
**Decision.** `create_store()` picks SQLite (default) or Postgres (`FAB_DATABASE_URL`, Supabase-ready:
psycopg 3, no prepared statements for the transaction pooler). The same contract tests run against both.
**Trade-off.** Two implementations to keep in step, which the shared test suite enforces.

### D8. SSE over the event log, not WebSockets or Supabase Realtime
**Context.** Vercel functions can't hold WebSockets. Supabase Realtime would lock the realtime path to
one vendor and wouldn't work locally without keys.
**Decision.** An append-only `shift_events` table, and SSE that tails it by id with `Last-Event-ID`
resume and a 25 s response window.
**Why.** Works identically on a laptop, in Docker and on serverless. Multi-instance fan-out is free
because the database is the bus. Polling the log every 0.5 s while a stream is open is cheap at
dashboard scale. Postgres `LISTEN/NOTIFY` is the upgrade if streams ever number in the thousands.

### D9. Server-owned clock, client-driven
**Decision.** The live shift's clock only moves when a client calls `advance`.
**Why.** No background process is needed, which suits serverless. In a real fab the clock would be wall
time and events would come from the MES; the same `report_job` / `advance` entry points would serve.

### D10. Stability penalty in live re-planning
**Decision.** Re-assigning a job away from its previous engineer costs `Weights.stability` (default 25).
**Why.** Re-optimising from scratch on every event produces "nervous" plans that would reshuffle the
whole floor for a 1% gain. People need plans that stay put.

### D11. Repair history: k-NN over Qdrant with a dependency-free embedder
**Decision.** Qdrant (embedded locally, server in production), hashed n-gram embeddings, and k-NN
regression for duration.
**Why.** Satisfies the "ML-based" option in a way that can be explained: every prediction comes with
the neighbours behind it. No model download, so it works offline and cold-starts fast.
`HashEmbedder` can be swapped for a neural model (e.g. fastembed) without changing anything else.
**Honest limit.** The history is synthetic. The pipeline is the deliverable, not the predictions.

### D12. Progressive, cancellable UI requests
**Decision.** One request per strategy, in parallel. Results render as they arrive, stale requests are
aborted, and the previous results stay on screen while new ones solve.
**Why.** Greedy answers in milliseconds and PyVRP in about a second. Waiting for the slowest would
waste the fast ones.

### D13. Light and dark themes with validated chart colours
**Decision.** Light is the default, with a toggle and system setting respected. Series and priority
colours were checked with a colour-vision validator in both themes. Where contrast is below 3:1, every
mark also has a direct label.
