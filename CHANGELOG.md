# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: SemVer.

## [Unreleased]

### Fixed
- **The static benchmark no longer assumes foresight of tool-downs.** Engineers leave the home bay
  just in time for their first job, so the slack before it is no longer charged as idle wait (every
  strategy and the exact solver share the change), and `python -m scripts.benchmark --mode revealed`
  replays each shift with tool-downs revealed at `reported_at`. Under revealed information 19 of 20
  cost differences against PyVRP include zero.
- **Benchmark accounting.** "Lowest cost" and the gap tables use the same objective (the total cost the
  solvers minimise); ALNS's search budget starts after its warm start, as PyVRP's does, and its
  annealing cools to near-greedy by the last iteration of any budget; every quality table carries a
  paired bootstrap 95% confidence interval; solve times are the median of five runs with the platform
  named; the gap report adds a column on the changeable cost; the scale study records time caps,
  iterations and cost per area and describes planning 222 areas, not re-planning; the certified bound
  runs several seeds and presets; `highspy` ships at runtime so the documented commands work.
- **Priority 3 means a tool-down on the constraint family**, nothing else; `critical_coverage_pct` is
  null when a shift has no such job instead of 100; new metrics `critical_jobs`,
  `workload_minutes_std` (the UI shows workload spread in minutes), `response_p95_min` and
  `unserved_downs`; the *Overstaffed* preset now adds a certified engineer (fab 2 gains the preset too; kept mild
  because every extra certified engineer multiplies the routes the exact proof enumerates).
- **Docs and citations.** The pinned PyVRP runs iterated local search (the DIMACS and EURO-NeurIPS wins
  belong to its hybrid genetic search); ReEvo, EoH and the EURO-NeurIPS competition point at the right
  papers; the technician-routing literature is cited and the "state of the art for this problem class"
  claim is scoped to the VRPTW core; ANALYSIS.md states what the model does not capture; the glossary
  and help articles fix fab terminology, the weight-tuning mechanisms and the hard-coded response
  window; DESIGN_REVIEW and DECISIONS no longer state generator constants as fab facts.
- **Assistant.** The optional LLM rewrite is checked against the grounded draft (ids, numbers and
  strategy names must come from it) and falls back with a reason; the recommendation is recomputed on
  the server instead of echoing the browser's text; "job 6", "E3" and "how long will J006 take" route
  correctly; glossary questions return the term asked; empty shifts get a plain answer, not a 500; the
  evaluation runs end to end over a harder set (paraphrases and off-topic questions that use app
  vocabulary) with before/after scores in `docs/ai.md`; feedback validates its intent, de-duplicates per
  user and question, and exports to new evaluation cases (`scripts/feedback_to_eval.py`).
- **Repair history.** No prediction below a similarity floor (weak matches are shown as such, and the
  planner keeps its standard estimate); the docs say what the retrieval is (lexical, hashed n-grams,
  Qdrant optional) and what leaves the server when the LLM is on.
- **Platform.** The UI image sends its security headers from every nginx location and runs nginx
  unprivileged on port 8080; the API sends a Content-Security-Policy and HSTS, with a dedicated policy
  for the API docs; live-shift streams use a 90-second ticket instead of the access token in the URL
  (the old form still works and logs a deprecation); guests may only change the live shifts they
  started; idle guest accounts are deleted after 30 days; stream opens are rate-limited and capped per
  user; anonymous calls no longer write rate-limit rows and expensive endpoints fail closed when the
  quota store is down; tokens must carry `exp` and bootstrap dispatchers a verified email.
- **Release pipeline.** A tag must be on `main` before images are built, and production is promoted
  only after a successful UAT deployment and smoke run of that commit; every workflow job has a
  timeout; every action is pinned to a commit; Dependabot watches Docker images; the uptime workflow
  creates its `incident` label before using it.
- **Frontend.** Benchmark verdicts use paired t intervals, Holm-adjusted across every comparison in the
  run, with a warning below ten seeds; weight sliders commit on release and identical solves share one
  request, with one retry after `Retry-After`; writes send `If-Match` and explain a 409; a 401 renews
  the session before signing out; absent metrics render as "n/a" rather than NaN; crash reports keep
  shift ids and e-mail addresses out of the issue body; contrast, reduced motion, live regions, tooltips
  and SVG labels meet WCAG AA, and the accessibility audit covers moderate issues, the phone layout and
  the dark theme; the heavy views load on demand.
- **The evidence base is tested.** Every study script behind `docs/ANALYSIS.md` (`benchmark`,
  `scale_study`, `certified_bound`, `duration_study`, `predictive_study`, `learned_policy_study`) and
  the UI-fixture export now have smoke tests that run their real entry points at a tiny size and check
  the tables' keys and that no heuristic beats a proven optimum (`tests/test_scripts.py`). Coverage
  counts `scripts/` as well as `app/`, with the CI floor set one point below the measured figure.
- **The exact solver is held to the hard constraints** on every preset of every fab (6 × 16), and the
  full-size (14 × 45) optimality proof now covers every preset, not only the normal shift.
- **Conventional-commit check** runs on pushes to `main` as well as pull requests, and no longer
  rejects commits that carry a `Co-authored-by` trailer (a trailer is provenance, not a format error).
- **README and docs numbers that had gone stale**: the test badge, the per-layer test counts and the
  reviewers' page are now checked by `tests/test_release.py` against the suites; the duplicated
  coverage percentages are replaced by the floors CI enforces.
- **Help articles**: *The five strategies* no longer recommends ALNS as "closest to optimal" on the
  strength of the 4 × 12 result the full-size proof overturned, and *Benchmark and optimality* says
  that the in-app *Measure gaps* is the small-shift study (the hosted API has a 60 s limit) and links
  to the full-size results.
- `docs/ONBOARDING_A_FAB.md` pointed at a pull request template that does not exist (only the issue
  template does); `docs/quickstart.md` no longer carries its own, different troubleshooting table.
- `THIRD_PARTY_NOTICES.md` lists highspy and scikit-learn (the dev dependencies behind ANALYSIS.md),
  the libraries bundled by `psycopg[binary]` and uvicorn's `[standard]` extras; the notices test now
  matches package names as tokens, not substrings, and covers `requirements-dev.txt` too.

### Changed
- SECURITY.md, the README and the deployment docs now say what row-level security, the CSP, the token
  storage, the rate limits and the "signed" images actually do; `.env.example` shows the `env:`
  indirection for tenant databases first; the privacy page covers guest deletion.
- `docs/ai.md` is rewritten around what the assistant and the repair index actually are, with the
  evaluation method and numbers; DECISIONS D24 and D30 and the design review follow.
- UI fixtures record the measured `runtime_ms` instead of hand-pinned values, with
  `frontend/src/test/fixtures/_export_meta.json` noting that the export runs at reduced solver
  budgets on the export machine; the fixture contract test also compares enum-like fields and whether
  lists have items, not only key sets and types.
- CI tests Python 3.13 (every minor from 3.11 to 3.14) and runs the component tests on Node 20, the
  oldest version the app claims to support. Slow tests (`pytest -m slow`) run on pushes to `main`.
- The README says that the production app's fast first load comes from a five-minute keep-warm cron,
  which also keeps the database from scaling to zero; the README's limitations point at the model's
  limits in ANALYSIS.md and at the hosted function limit that confines the live *Measure gaps* to
  small shifts.

### Added
- `scripts/*`: size flags for every study (`--only`, `--gap-size`, `--scaling-sizes`,
  `--budget-seeds`; `--areas`, `--area-size`, `--events`, `--sizes`; `--train-n`, `--test-n`,
  `--gbm-iters`, `--fab`; `--engineers`, `--jobs`), each defaulting to the published study.
- A slow test running ALNS and PyVRP at the shipped iteration budgets on a full shift: hard
  constraints, determinism across two runs, and cost no worse than at the test budget.
- `make slow`, and `CONTRIBUTING.md` states that commit trailers are allowed and that the history
  before v2.9.0 was authored in batches and rewritten.

## [2.8.0] - 2026-10-06

### Added
- **Three industrial-AI studies** (`docs/ANALYSIS.md`, "Industrial AI"), each reproducible with one script:
  - `scripts/duration_study.py`: repair-time estimates on 600 held-out repairs per fab. No model beats
    the standard estimate (about 32 min mean error) because symptoms don't reveal the root cause; the
    history's value is a calibrated P90 (90.5% coverage).
  - `scripts/predictive_study.py`: a mock failure-prediction feed replayed through live dispatch. At 60%
    recall and 90 minutes' lead, unplanned downtime falls by about 1,550 minutes per shift (95% CI
    1,413 to 1,687); recall matters most, lead time saturates past about 90 minutes.
  - `scripts/learned_policy_study.py`: a dispatch order learned by policy search, scored against proven
    optima. 20.4% mean gap versus 27.4% for the hand-written rule; search methods stay far ahead (PyVRP 2.8%).

### Fixed
- The help article and generator no longer imply that history-predicted durations are more accurate
  than the standard estimate; they now state the measured result.

## [2.7.4] - 2026-10-05

### Fixed
- **Shift sizes are checked in the form.** Seed, engineers and jobs outside the live demo's limits
  (engineers 1–60, jobs 1–200) now get a plain message under the fields, and *Generate shift* stays
  disabled until they are fixed, instead of a raw "Input should be less than or equal to 60" banner.
  Larger organisations are covered by the offline scale study (ANALYSIS.md, Scale).

## [2.7.3] - 2026-10-05

### Fixed
- **Choosing a preset now generates that shift.** Before, the header switched to the new preset while
  the results still showed the previous shift until *Generate shift* was pressed. The header chips now
  always describe the shift on screen.
- **The cost × latency chart explains points off the frontier.** A hollow point now has a dashed line
  to the strategy that beats it on both cost and speed, and a note saying so ("beaten by Greedy on
  cost and speed"), so it no longer looks disconnected by mistake.

## [2.7.2] - 2026-10-03

### Fixed
- **Slow first load (20–30 s when the servers were cold).** The page no longer waits for the
  sign-in settings: a returning browser starts from the last ones it saw and refreshes them in the
  background, and the sign-in library loads in parallel. The signed-in user is checked once, not
  twice (Supabase announces the same session more than once). The API starts about 4× faster:
  SciPy and PyVRP load when something is first solved, not at startup. A ping every five minutes
  keeps one instance and both databases warm.

## [2.7.1] - 2026-10-02

### Added
- `FAB_TENANT_DATABASES` values can be `env:VAR`: the fab's database URL is read from a variable a
  hosting integration injects (e.g. Neon through Vercel), so nobody copies the secret. A missing
  variable fails at startup, not at the first request.

### Fixed
- Postgres URLs keep `channel_binding` (Neon sets `require`), which protects the password exchange;
  it was being dropped with unknown parameters.

## [2.7.0] - 2026-10-02

### Added
- **A database per fab** (`FAB_TENANT_DATABASES`): each listed fab's shifts, events, assignments,
  replays and cached plans live only in its own database; the default database keeps user-level
  data. Health, retention and account deletion cover every database.
- Shift ids carry their fab (`fab1-300mm-logic.3f2a…`), so requests route to the right database
  without a lookup.
- Isolation tests that read each database directly, on SQLite and on separate Postgres databases,
  and a CI job that starts one Postgres per fab (`docker-compose.fabs.yml`) and checks each fab's
  rows exist only in its own database. Decision D34.

## [2.6.1] - 2026-10-02

### Added
- **Certified bounds at scale** (`scripts/certified_bound.py`): column generation over all routes
  gives a lower bound no plan can beat. At 30 × 100 (8.3 million routes) the optimum lies between
  1828.0 and 1844.3; PyVRP is within 8.4% of it, ALNS within 15.4%.
- **Scale study** (`scripts/scale_study.py`): a 20,000-engineer company re-plans in 47 s on one laptop
  (222 areas in parallel); a live tool-down re-plans in 217 ms (p95 270 ms).
- ANALYSIS "Scale" section and ARCHITECTURE "Scaling to an enterprise", with these measurements.

### Found
- Heuristic gaps grow with problem size (PyVRP 2.7% at 14 × 45, about 8% at 30 × 100), and ALNS
  returns its regret-2 start unchanged from 150 × 500 up: decomposition into areas is required.

## [2.6.0] - 2026-10-02

### Added
- **Proven optimum at full shift size.** The exact solver (route enumeration + set-partitioning
  MILP) now handles 14 engineers × 45 jobs: about 34,000 routes, solved to proven optimality in 20 s
  on average (138 s worst). New study: `python -m scripts.benchmark --only gaps-full`.

### Changed
- **Every gap is now measured at full size** (80 shifts, all proven optimal): PyVRP 2.7%, ALNS
  5.7%, Regret-2 19.4%, Hungarian 25.8%, Greedy 28.1%. The earlier small-shift figures (ALNS 0.9%)
  understated the gaps; README, analysis, help and decisions now use the full-size numbers.
- The exact solver uses a sparse constraint matrix and guards on route count instead of job count.

## [2.5.1] - 2026-10-02

### Changed
- **Sign-in is passwordless.** Email sign-in is one step for new and returning users: enter your
  email and type the one-time code that arrives (or open the link in the same email). The
  "Use a password instead" option is gone: there is no sign-up, so nobody had a password to use.
  After a code is sent, the button offers to send a new one.

## [2.5.0] - 2026-10-01

### Added
- **Equipment ingestion API** (`POST /api/ingest/tool-downs`): tools and MES systems report faults
  directly, authenticated by a per-fab token (only its SHA-256 is configured), with a required
  `Idempotency-Key` so retried messages report once. The fault joins the fab's live shift.
- **Assignments read model**: every write to a shift also writes its per-job rows (engineer, times,
  status) in the same transaction. New queries: `GET /api/shifts/{id}/assignments` and an
  engineer's history, `GET /api/fabs/{fab}/engineers/{id}/assignments`.
- **Self-serve account deletion** (user menu → Delete my account; `DELETE /api/auth/me`): personal
  data is erased, shift history is anonymised, and the sign-in account is removed.
- **Terms of use**, linked from sign-in and About & support.
- **Architecture: design principles and trade-offs**, with the next step for each at fab scale;
  decisions D28–D32.

### Changed
- **Rate limits hold across instances**: a per-minute quota in the database backs the in-memory
  burst guard, so limits apply on serverless; it fails open if the database is unreachable.
- **Tenant scope enforced in SQL**: shift reads are filtered by the caller's fabs in the query, as
  well as checked in the route.
- **Live updates poll adaptively**: 0.25 s while a shift is busy, backing off to 2 s when quiet.
- **Repair-history search is exact NumPy k-NN by default** (index builds in 80 ms instead of
  ~600 ms, ~0.1 ms per query); Qdrant is used when a server is configured.

### Fixed
- A symptom sharing nothing with past repairs produced a 0-minute "prediction"; it now returns none.
- Repair-history answers are reproducible: ties between equally similar repairs break by id.

## [2.4.0] - 2026-10-01

### Added
- **CodeQL** security analysis of the Python and JavaScript code on every pull request, every push
  to `main` and weekly (`security-extended` queries).
- **Dependency review** on pull requests: a new dependency with a high-severity vulnerability, or
  under a GPL-family or SSPL license, fails the check.
- **The Docker stack is run in CI, not just built**: it starts Postgres, Qdrant, the API and nginx,
  checks health, signs in and calls the API, then **Trivy** scans both images for fixable critical
  and high vulnerabilities.
- **actionlint** (with shellcheck) on every workflow, **Conventional Commits** and single-author
  checks on pull requests, and a timeout on every job.
- **Signed release images** on GitHub Container Registry (`ghcr.io/pavansky/fab-dispatch-api`,
  `-ui`), with an SBOM and build provenance you can verify with `gh attestation verify`.
- **Releases confirm production:** the release waits until production reports the new version,
  healthy with its schema current, before publishing release notes.

### Fixed
- `docker compose up` failed to start: the API refused demo sign-in in its production mode. The
  stack now runs with demo sign-in enabled explicitly.
- Container images carried known, fixable vulnerabilities: OS packages are now updated at build
  time, the UI image moves to nginx 1.29, and the API image uses Debian's maintained `libpq5`
  instead of the copy bundled in `psycopg[binary]`. Both images scan clean.
- The post-deploy smoke test ran against GitHub Pages deployments of the docs site.

## [2.3.1] - 2026-10-01

### Added
- **MIT License** (`LICENSE`), shown in the README, the documentation site, the app's
  **About & support** panel, both package manifests and the container image labels.
- **Third-party notices** (`THIRD_PARTY_NOTICES.md`): every runtime dependency with its license,
  including a note on psycopg (LGPL-3.0, used unmodified). A test fails if a new dependency isn't
  listed, so the notices can't drift.

## [2.3.0] - 2026-10-01

### Added
- **One-command start:** `python3 run.py` checks Python and Node, installs what's missing (once),
  starts the API and UI together and opens the browser; Ctrl-C stops both. Also `make start`.
- **GitHub Codespaces:** run the whole app in the browser with nothing installed (`.devcontainer/`).
- **Documentation site** on GitHub Pages: user guide (generated from the in-app help articles),
  quick start, a reviewers' tour, architecture, algorithms, decisions, operations, AI transparency,
  privacy, support, changelog, and an API reference rendered from the live OpenAPI schema. Built
  strictly on every PR, published from `main`.
- **API reference in production** at `/api/docs` (and `/api/redoc`, `/api/openapi.json`).
- **About & support** panel: release, build, environment, live status, and every documentation and
  support link, including **Report a problem** with the release and browser prefilled.
- **Crash screen:** a render error shows a way forward and a prefilled report, not a blank page.
- **Assistant feedback:** 👍/👎 (with an optional note) on every answer, stored with the user id for
  180 days; dispatchers get helpful rates by kind of question (`/api/assistant/stats`). One structured
  log line per answer. A "Support and feedback" help article; the evaluation set grows to 42 questions.
- **Accessibility checks:** axe-core WCAG 2.1 A/AA audits of every screen and panel in the end-to-end suite.
- **Operations:** an uptime check every 30 minutes that opens an incident issue on failure and closes
  it on recovery; the assistant evaluation report in every CI summary.
- **Support:** `SUPPORT.md`, feature-request template, contact links (Discussions, docs, security).
- One release version everywhere (`app/version.py`, both manifests, this changelog), checked by a test;
  `/api/health` and `/api/meta` report the release and commit.

### Fixed
- Accessibility: muted text and the active tab number now meet WCAG AA contrast; contextual help no
  longer nests a button inside `<summary>`; the floor plan is a labelled group of controls, not an
  image; scrollable tables are keyboard-reachable; the schedule's rows have proper cells.

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
