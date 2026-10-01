# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: SemVer.

## [2.2.1] - 2026-10-01

### Fixed
- Signing in with the emailed code only accepted 6 digits, but Supabase's code length is a project
  setting (6 to 10; this project sends 8), so the code could never be entered. The field now accepts
  6 to 10 digits.

## [2.2.0] - 2026-10-01

### Added
- **CAPTCHA on sign-in** (Cloudflare Turnstile, free): when `FAB_TURNSTILE_SITE_KEY` is set, the
  sign-in screen loads the widget (usually invisible) and sends its token with guest, magic-link and
  password sign-ins; Supabase Auth verifies it. Off, and not loaded, without the key.

### Changed
- The Content-Security-Policy allows Cloudflare's challenge script and frame. A test now fails if
  the policy served by Vercel, nginx and the Vite preview ever differ.
- Sign-in emails come from "Fab Dispatch by PavanSky".

## [2.1.0] - 2026-10-01

### Added
- **Help center:** 16 searchable articles (getting started, every view, strategies, constraints,
  metrics, live dispatch, roles, fabs, glossary, FAQ, shortcuts), contextual ⓘ links next to controls,
  a first-run tour, keyboard shortcuts (`?` help, `/` assistant, `1`–`6` views) and `?help=` deep links.
- **Ask Dispatch,** an assistant that answers about the shift on screen and the app from the help
  articles and the real plans, with sources and actions, and says "I don't know" otherwise. Local and
  keyless; an optional LLM (`anthropic` or local `ollama`) can reword answers. Its quality is measured on
  an evaluation set in CI.
- **Guest access:** "Try it as a guest" (Supabase anonymous sign-in), role set by `FAB_GUEST_ROLE`.
- **Sign in with the code** from the email, as well as the link.
- **Branded auth emails** (six templates, generated from one layout) and setup guide in `supabase/`.
- **Brand assets:** favicon, app icons, web manifest and a link-preview card for shared links.

### Fixed
- On phones, several views were wider than the screen and scrolled sideways (grid columns couldn't
  shrink below their content). The phone end-to-end test now measures against the real screen width.
- Contextual help never sits inside a label or heading, keeping their accessible names clean.

## [2.0.3] - 2026-10-01

### Security
- App tables were readable (and possibly writable) through Supabase's public Data API with the
  publishable key, because Supabase grants its API roles access to new tables in `public` by
  default. Migration 3 enables row-level security on every app table and revokes the `anon` and
  `authenticated` roles' access; the service connects as the table owner and is unaffected. The
  post-deploy smoke test now fails if any app table is readable with the public key.

## [2.0.2] - 2026-10-01

### Added
- **Frontend component tests** (Vitest + Testing Library, 70 tests): sign-in, every view, live
  dispatch with a simulated event stream, roles, theme, fab switching. They render JSON captured
  from the real API, and a backend contract test fails if the API's shapes drift from it.
- **End-to-end tests** (Playwright, 19 tests): the real API and UI in Chromium on desktop and a phone
  viewport, including a viewer in a second browser watching a dispatcher's live shift. Every test
  fails on a browser console error. Runs in CI and uploads traces on failure.
- Coverage floors for the UI; API coverage now measured with Postgres (94%), floor raised to 90%.
- Floor plan jobs and engineers are keyboard- and screen-reader-accessible buttons.

### Fixed
- Rejoining a live shift after leaving it showed nothing (a cached ETag got a 304 with no view to keep).
- On phones the top bar overflowed, hiding the user menu (and sign-out); the theme switch now
  moves into the user menu below 640px.
- Cached plans are cleared on sign-out, so the next session on the same browser starts clean.

### Changed
- README: quick start first, tested on macOS/Linux and Windows; a 5-minute tour of the app; a
  requirements map from the brief to the app and code; troubleshooting; the three test layers.
- Frontend declares its Node requirement (`>=20.19`, from Vite 7).
- Repository is public, with branch protection on `main` (CI must pass) and `production`.

## [2.0.1] - 2026-10-01

### Fixed
- Post-deploy smoke test checks production on its public domain. It previously targeted the
  per-deployment URL, which Vercel Authentication protects, so production checks were skipped.
  A production smoke test can no longer pass by skipping.

## [2.0.0] - 2026-10-01

### Added
- **Multi-fab**: site-specific data moved into validated fab profiles; a second fab (200mm analog,
  8-hour shifts, photo constraint) ships alongside; fab switcher in the UI; per-fab repair history.
- **Authentication and roles**: Supabase Auth in UAT/production (magic link or password), demo sign-in
  for local development, `viewer` and `dispatcher` roles, per-user fab access.
- **Real-time hardening**: one clock driver at a time (lease), idempotency keys on live actions,
  presence ("who's watching"), recent shifts to rejoin, actor on every event, offline banner, toasts.
- **Environment isolation**: `FAB_DB_SCHEMA` puts each environment in its own Postgres schema, so
  UAT (`uat`) and production (`public`) share the free-tier Supabase database without sharing data.
- **Platform**: versioned database migrations with an advisory lock; `schema_ok` in health;
  daily data retention via Vercel Cron; strict security headers (CSP, HSTS, Permissions-Policy).
- **Delivery**: CI with lint, format, coverage floor, Python 3.11/3.12/3.14, Postgres, frontend
  lint/tests/build, dependency audits and image builds; release workflow promoting tagged commits
  from `main` (UAT) to `production`; post-deploy smoke tests; Dependabot; pre-commit; PR and issue
  templates; CODEOWNERS.
- Mobile and tablet layouts: drawer controls, scrollable tabs, touch-friendly floor plan.
- Docs: environments and release runbook, fab onboarding guide, contributing guide.

### Changed
- **Breaking:** all planning, live and repair endpoints require authentication; scenarios carry a
  `fab_id`; listing shifts needs `fab_id`.
- Light theme is the default; dark and auto (follow the OS) are opt-in.

### Fixed
- `PyJWT` declared as a runtime dependency (it was only installed locally).

### Security
- Vitest upgraded to 5.x (moderate advisory in the test runner); both dependency trees audit clean.

## [1.2.0] - 2026-10-01

### Added
- Shareable deep links: `?tab=` opens a view, `?job=` / `?engineer=` open with that item selected; the
  URL follows navigation.
- Production README with screenshots, results, API reference and configuration table.

### Fixed
- A deep-linked selection is no longer cleared when the first scenario loads.

## [1.1.1] - 2026-10-01

### Fixed
- Installs and runs on Python 3.11 (numpy/scipy use compatible ranges); CI tests 3.11, 3.12 and 3.14.
- Recommendation panel stacks on narrower screens instead of squeezing text.
- Opening the API root shows where the docs and UI are instead of a 404.
- Removed a stray build binary from the repository and its history.

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

## Pre-releases

- **0.4.0**: progressive per-strategy solving, live dispatch over SSE, repair-history insights in the UI.
- **0.3.0**: PyVRP and ALNS solvers, exact MILP baseline, live re-dispatch, SQLite/Postgres store, plan cache.
- **0.2.0**: dispatch console UI with light/dark themes, goal-based recommendation, benchmark view.
- **0.1.0**: allocation engine with greedy, Hungarian and regret-2 strategies; React floor-plan UI; tests.
