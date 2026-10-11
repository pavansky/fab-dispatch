# Third-party software

Fab Dispatch is [MIT licensed](LICENSE). It is built on the open-source software below, each under
its own license; this file lists what the app ships with. Every license here allows use in an MIT
project, commercial use included. The data in the app is synthetic, made for this project, and
covered by the MIT license too.

## Runtime: API

| Package | Used for | License |
|---|---|---|
| [fastapi](https://github.com/fastapi/fastapi) | HTTP API | MIT |
| [uvicorn](https://github.com/encode/uvicorn) | ASGI server | BSD-3-Clause |
| uvicorn's `[standard]` extras: [uvloop](https://github.com/MagicStack/uvloop), [httptools](https://github.com/MagicStack/httptools), [websockets](https://github.com/python-websockets/websockets), [watchfiles](https://github.com/samuelcolvin/watchfiles) | Faster event loop, HTTP parsing, WebSockets, auto-reload | uvloop: MIT or Apache-2.0; httptools: MIT; websockets: BSD-3-Clause; watchfiles: MIT |
| [pydantic](https://github.com/pydantic/pydantic) | Validation and models | MIT |
| [pydantic-settings](https://github.com/pydantic/pydantic-settings) | Configuration from the environment | MIT |
| [numpy](https://github.com/numpy/numpy) | Numerics | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) |
| [scipy](https://github.com/scipy/scipy) | Hungarian assignment, exact MILP (HiGHS, MIT) | BSD-3-Clause |
| [pyvrp](https://github.com/PyVRP/PyVRP) | Vehicle-routing solver strategy | MIT |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | Vector search for the assistant and repair history | Apache-2.0 |
| [pyjwt](https://github.com/jpadilla/pyjwt) with [cryptography](https://github.com/pyca/cryptography) | Verifying sign-in tokens | MIT; cryptography: Apache-2.0 or BSD-3-Clause |
| [psycopg](https://github.com/psycopg/psycopg) | Postgres driver (production) | LGPL-3.0-only, see below |

**psycopg (LGPL-3.0).** Used unmodified, as a separately installed library the app imports. Under
the LGPL that places no conditions on Fab Dispatch's own code, and you can swap in any other build of
psycopg. Its source is at the link above. The default local setup (SQLite) doesn't load it at all.
The `psycopg[binary]` wheel the app installs bundles [libpq](https://www.postgresql.org/) (the
PostgreSQL License, a permissive MIT-style license) and [OpenSSL](https://www.openssl.org/)
(Apache-2.0).

## Runtime: web app

| Package | Used for | License |
|---|---|---|
| [react](https://github.com/facebook/react) and [react-dom](https://github.com/facebook/react) | UI | MIT |
| [@supabase/supabase-js](https://github.com/supabase/supabase-js) | Sign-in | MIT |
| [react-markdown](https://github.com/remarkjs/react-markdown) | Rendering help articles | MIT |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | Tables and lists in help articles | MIT |
| [Geist and Geist Mono](https://github.com/vercel/geist-font) | Typefaces, served by Google Fonts | SIL Open Font License 1.1 |

## Documentation site and development tools

Used to build, test and document the project, not shipped with the app:
[MkDocs](https://github.com/mkdocs/mkdocs) (BSD-2-Clause),
[Material for MkDocs](https://github.com/squidfunk/mkdocs-material) (MIT),
[Redoc](https://github.com/Redocly/redoc) (MIT), [Vite](https://github.com/vitejs/vite) (MIT),
[Vitest](https://github.com/vitest-dev/vitest) (MIT), [Playwright](https://github.com/microsoft/playwright) (Apache-2.0),
[axe-core](https://github.com/dequelabs/axe-core) (MPL-2.0) and [ESLint](https://github.com/eslint/eslint) (MIT).

The Python development dependencies (`backend/requirements-dev.txt`). Two of them produce numbers
in [docs/ANALYSIS.md](docs/ANALYSIS.md) rather than test the app, so they are listed with the same
care as the runtime:

| Package | Used for | License |
|---|---|---|
| [pytest](https://github.com/pytest-dev/pytest) and [pytest-cov](https://github.com/pytest-dev/pytest-cov) | Test runner and coverage | MIT |
| [httpx](https://github.com/encode/httpx) | In-process API client in the tests | BSD-3-Clause |
| [ruff](https://github.com/astral-sh/ruff) | Lint and format | MIT |
| [pip-audit](https://github.com/pypa/pip-audit) | Known-vulnerability scan | Apache-2.0 |
| [pyyaml](https://github.com/yaml/pyyaml) | Reading `mkdocs.yml` in the docs-site test | MIT |
| [highspy](https://github.com/ERGO-Code/HiGHS) | Certified optimality bounds by column generation (`scripts/certified_bound.py`, ANALYSIS.md) | MIT |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | Classifier and quantile trees in the repair-duration study (`scripts/duration_study.py`, ANALYSIS.md) | BSD-3-Clause |

## Complete lists

The tables above cover direct dependencies. Each one brings its own dependencies, under their own
licenses. For the full list of an installed copy:

```bash
pip install pip-licenses && pip-licenses --from=mixed   # API (in backend/.venv)
npx license-checker --production --summary              # web app (in frontend/)
```

## Hosted services

The production deployment uses Vercel (hosting), Supabase (database and sign-in) and Cloudflare
Turnstile (bot check) on their free tiers, under each provider's terms of service. None of them is
needed to run the app locally.
