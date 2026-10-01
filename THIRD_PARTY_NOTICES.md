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

## Runtime: web app

| Package | Used for | License |
|---|---|---|
| [react](https://github.com/facebook/react) and react-dom | UI | MIT |
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
[axe-core](https://github.com/dequelabs/axe-core) (MPL-2.0), [pytest](https://github.com/pytest-dev/pytest) (MIT),
[ruff](https://github.com/astral-sh/ruff) (MIT) and [ESLint](https://github.com/eslint/eslint) (MIT).

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
