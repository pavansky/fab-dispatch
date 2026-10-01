# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: SemVer.

## [1.1.0] - 2026-10-01

### Added
- Best-value recommendation (coverage guard → noise margin → fastest), set as the default goal.
- Cost × latency frontier chart on the Overview and per benchmark preset.
- Paired bootstrap 95% CIs in the benchmark: a strategy is "worse" only when the CI excludes zero.
- Reads `POSTGRES_URL` from Vercel's Supabase integration; libpq-safe URL cleaning.

### Changed
- New visual system: warm neutrals, Geist/Geist Mono, single orange signal, light and dark.
- Embedded Qdrant runs in memory per process by default.

### Fixed
- 500 on repair search when a second process held the embedded Qdrant folder lock.
- Vercel build had no Python dependencies (pyproject listed none); now kept in sync with
  requirements.txt by a test.

## [1.0.0] - 2026-10-01

### Added
- Fab maintenance domain: engineers with tool-family certifications (levels 1–3), tool-downs and PMs
  with start windows and priorities, Manhattan walking on a floor plan.
- Shared constraint engine with route insertion, explanations and rejection reasons.
- Strategies: greedy, Hungarian in rounds, regret-2, ALNS, PyVRP iterated local search; plus an exact
  set-partitioning MILP for optimality gaps.
- Live dispatch: rolling-horizon re-planning with frozen work and a stability penalty, optimistic
  versioning, event log, SSE streaming, shareable shift links.
- Repair-history retrieval on Qdrant: k-NN duration prediction, likely cause, experienced engineers;
  optional history-predicted durations for planning.
- Two-tier content-addressed plan cache; ETags; gzip; rate limits; request IDs; JSON logs; health checks.
- SQLite (local) and Postgres/Supabase (production) stores behind one interface.
- React UI: overview with goal-based recommendation, floor plan, inspector, schedule, workforce,
  live dispatch, benchmark; light and dark themes.
- Docker images, compose stack, Vercel config, CI workflow, Makefile.
- Docs: analysis, architecture, decisions, deployment, security.
