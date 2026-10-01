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

### D13. Visual system: one ink, one signal
**Decision.** Warm neutrals, Geist and Geist Mono, hairline rules, square corners, and a single orange
signal colour for what deserves attention: the recommended plan, live state, bottleneck work. Light by
default, a separately tuned dark theme, and the system setting is respected.
**Why.** Five hues for five strategies competed with the content. Every strategy is already named on
its mark, so colour can do one job, "this is the recommendation", instead of five. Contrast was checked
for both themes, with the orange stepped darker for text on light backgrounds (5.4:1).

### D14. "Best value" recommendations that refuse false positives
**Context.** Cost, latency and coverage pull against each other, and on a single shift small cost
differences are mostly noise.
**Decision.** The default goal applies three steps in order:
1. Never give up bottleneck or priority coverage.
2. Treat every plan within a noise margin (2% or 5 points) of the cheapest as equally cheap.
3. Among those, pick the fastest to compute.

The benchmark goes further: a strategy is only "worse" when the paired bootstrap 95% CI of its cost
difference against the best excludes zero. Otherwise it's reported as tied.
**Why.** Paying 1 s of latency for a 1% "saving" that wouldn't replicate is the false positive to
avoid. A slower solver has to earn its latency with a difference that is real.

### D15. Embedded Qdrant is in-memory per process
**Context.** On-disk embedded Qdrant locks its folder exclusively, so a second process (a reloader,
a second uvicorn worker, a second container) failed with 500s.
**Decision.** In memory by default. The index is deterministic and rebuilds in about 0.6 s. On-disk is
opt-in (`FAB_QDRANT_PATH`) and falls back to memory if locked. Shared state belongs on a Qdrant server
(`FAB_QDRANT_URL`).

### D16. Search budgets sized from the quality curve, not by feel
**Context.** On Vercel, PyVRP at 3000 iterations hit the 3 s cap: slower, non-reproducible, and
uncacheable.
**Decision.** ALNS 300 and PyVRP 1000 iterations, the knee of the measured curve. Going higher triples
latency for a further 0.2–3.9% cost. Configurable, and part of the cache key.

### D17. Fab-specific knowledge is data (fab profiles), not code
**Context.** The first build hard-coded one fab: its floor, tool families, shift and fault
catalogue. Each new customer site would have meant a code change and a release.
**Decision.** One validated JSON profile per fab (`backend/app/fabs/profiles`). The generator, repair
history, API and UI all read it. A second, deliberately different fab (200mm, 8-hour shifts, photo as
the constraint) ships alongside to prove the engine is generic. Fab 1 was converted with a golden
test proving its generated scenarios are byte-identical to the old hard-coded generator.
**Trade-off.** Profile authors must describe the floor and fault catalogue. The onboarding guide and
schema validation keep that tractable.

### D18. Authentication via a managed identity provider; demo sign-in only locally
**Decision.** Supabase Auth in UAT and production. The API verifies Supabase-issued tokens: JWKS for
asymmetric keys, falling back to the legacy HS256 secret. Locally, a one-click demo sign-in keeps the
"runs locally with no keys" requirement. Settings **refuse** demo mode in production unless
explicitly allowed with a non-default secret (fail closed).
**Why.** Passwords, resets, magic links and MFA are a product in their own right; storing passwords
here would add risk and no value. Roles (`viewer` < `dispatcher`) and fab access come from
`app_metadata`, which users can't edit, with an email allow-list to bootstrap the first dispatchers.

### D19. Tenancy by fab, and 404 rather than 403 across tenants
**Decision.** Every fab-specific request and every live shift is checked against the user's fab
list. A shift or fab outside it returns **404**, so one customer can't confirm another's fab exists.

### D20. Versioned, additive migrations under an advisory lock
**Decision.** Numbered migrations recorded in `schema_migrations`, applied at startup under a
Postgres advisory lock. Additive only; destructive changes are split across releases. Health
reports `schema_ok`, which the post-deploy smoke test checks.
**Why.** "Create if missing" can't evolve a schema. A runner that serialises serverless cold starts
and is visible in health checks can.

### D21. Real-time safety: clock lease, idempotency keys, presence
**Decision.** Only one dispatcher drives a shift's clock: a 20 s lease, renewed by each tick and
released on pause. Mutating live calls accept an `Idempotency-Key`; a retry returns the first
response. Open SSE streams heartbeat presence.
**Why.** Two people pressing Play, or a flaky network retrying "advance 60 minutes", would otherwise
corrupt the shift. These are the failure modes of a multi-user real-time tool.

### D22. Promotion pipeline: main is UAT, tags are production
**Decision.** Pull requests get CI and a preview deploy. `main` deploys to UAT (its own database).
A SemVer tag re-runs CI on that commit, must already be on `main`, and fast-forwards the
`production` branch that Vercel deploys from. Every deployment is smoke-tested.
**Why.** Nothing reaches production without passing UAT and CI on the exact commit. Rollback is
promoting the previous deployment, and production can't move backwards by accident.

### D23. Three test layers; the UI is tested against captured API responses
**Decision.** pytest for the engine and API; Vitest + Testing Library for components, rendering JSON
exported from the real API (`scripts/export_ui_fixtures.py`) behind a fake `fetch`; Playwright for
end-to-end flows against the real API and UI on desktop and a phone viewport. A backend test
compares the committed fixtures' shape with live responses. Tests query by role and accessible name,
not CSS classes.
**Why.** Hand-written mocks drift silently from the API, so component tests pass against data that
no longer exists; the contract test turns that drift into a failure. Component tests are fast and
precise; only a browser proves SSE, the Vite proxy, layout and touch work together. Querying by role
keeps the UI accessible: the floor plan's jobs became real buttons because the tests needed them to be.

### D24. A grounded assistant: retrieval and tools first, an LLM only to reword
**Decision.** The assistant classifies the question, then answers only from tools: retrieval over the
help articles (hybrid: vectors in Qdrant plus keyword, heading and section-text matches) and the
planning service for the shift on screen. Every answer carries citations and actions. Below a
measured retrieval score it says "I don't know". An LLM is optional and only rewords the grounded
answer; citations and actions never come from it.
**Why.** A dispatcher acts on these answers, so a confident wrong one is worse than none. Grounding
makes answers checkable and identical to what the screen shows; the refusal threshold sits between
on-topic (≥ 0.65) and off-topic (≤ 0.36) scores on an evaluation set that runs in CI. It also meets
the brief's no-keys rule, and makes the LLM a swappable enhancement, not a dependency.

### D25. One-click guest access for the public demo
**Decision.** Supabase anonymous sign-in behind a "Try it as a guest" button; guests get
`FAB_GUEST_ROLE` (dispatcher on the public demo, viewer by default, or refused).
**Why.** Supabase's built-in email sender only reaches the project's own team, and a reviewer
shouldn't depend on email at all. Anonymous users are real Supabase users, so the API's verification,
rate limits and fab scoping apply unchanged, and a guest can't escalate.
