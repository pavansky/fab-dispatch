# Deployment

For the dev → UAT → production flow, promotion and rollback, see [ENVIRONMENTS.md](ENVIRONMENTS.md).

Three ways to run it, in increasing order of production-likeness. All use free and open-source software.

## 1. Local (default)

See the README quick start. SQLite at `backend/data/fab.db` (created on first use) and an
in-memory Qdrant index built on first query (~0.6 s). No configuration needed.

## 2. Docker Compose (production-like)

```bash
docker compose up --build        # http://localhost:8080
docker compose down -v           # stop and delete volumes
```

The stack signs in with one-click demo accounts. Each release also publishes signed images:
`ghcr.io/pavansky/fab-dispatch-api` and `ghcr.io/pavansky/fab-dispatch-ui`, tagged with the version
and `latest`. Check where one came from with
`gh attestation verify oci://ghcr.io/pavansky/fab-dispatch-api:latest -R pavansky/fab-dispatch`.

| Service | Image | Notes |
|---|---|---|
| `postgres` | postgres:16-alpine | volume `pgdata`, healthcheck |
| `qdrant` | qdrant/qdrant:v1.19.0 | volume `qdrant` |
| `api` | `backend/Dockerfile` | python:3.12-slim, non-root, 2 uvicorn workers, JSON logs, healthcheck on `/api/livez` |
| `web` | `frontend/Dockerfile` | nginx serving the Vite build. Proxies `/api` with SSE buffering off and caches hashed assets for a year |

## 3. Vercel + Supabase (+ Qdrant Cloud, optional)

**Current production:** https://fab-dispatch.vercel.app (Vercel project `fab-dispatch`, auto-deploys from
`main`). The database is Supabase `fab-dispatch` on the free plan, created through Vercel → Storage →
Supabase and hosted in Washington DC (`iad1`), the same region as the API functions, to keep query
latency low. The integration injects `POSTGRES_URL`, which the app reads. Access is behind Vercel
Authentication (deployment protection) until it's opened to reviewers.


`vercel.json` defines two **Services** in one project: `web` (Vite, `frontend/`) and `api` (FastAPI,
`backend/`, entrypoint `app.main:app`). `/api/*` goes to the API and everything else to the UI. The API
receives the original `/api/...` path, so routes need no changes.

### Steps
1. **Supabase** (free tier): create a project, then copy the **transaction pooler** connection string
   (port 6543) from *Project Settings → Database*. The schema is created automatically on first request.
2. **Qdrant Cloud** (optional, free tier): create a cluster and copy its URL and API key. Without it, the
   repair index runs in memory in each instance (rebuilt on cold start in about 0.6 s).
3. **Vercel**: import the repository (or run `vercel link` then `vercel deploy`), and set the environment
   variables:

| Variable | Value |
|---|---|
| `FAB_DATABASE_URL` | Supabase pooled URL. Or skip it and connect Supabase through Vercel's Storage integration: the app also reads the `POSTGRES_URL` it injects, and strips the `supa=` parameter libpq rejects |
| `FAB_QDRANT_URL`, `FAB_QDRANT_API_KEY` | optional: repair search on a Qdrant server (exact NumPy search otherwise) |
| `FAB_TENANT_DATABASES` | optional: `{"<fab id>": "<database URL>"}` gives that fab its own database |
| `FAB_INGEST_TOKENS` | optional: `{"<fab id>": "<sha256 of token>"}` enables equipment ingestion for that fab |
| `FAB_CORS_ORIGINS` | not needed: same origin |

4. Deploy and check `https://<app>/api/health` → `{"status":"ok","db_ok":true}`.

### Serverless behaviour, by design
- **Without `FAB_DATABASE_URL`** the app still boots, using SQLite in `/tmp` per instance. That's fine for a
  demo, but live shifts won't be shared across instances. Set it for production.
- **SSE** responses close after 25 s and browsers reconnect with `Last-Event-ID`. This stays well under
  the function duration limit (`maxDuration: 60`).
- **Benchmark** requests are per preset, so each finishes in well under a minute.
- **Rate limits** are per instance (in memory): a guard against runaway clients, not a quota system.
  Use Vercel's firewall for edge rate limiting.
- **Bundle**: the runtime requirements install to about 320 MB (measured; SciPy and gRPC are the largest),
  under Vercel's 500 MB Python limit.

### If Services (beta) isn't enabled on the account
Deploy two projects from the same repository instead:
- **API project**: root `backend/`. Set the variables above, plus `FAB_CORS_ORIGINS=["https://<web-domain>"]`.
- **Web project**: root `frontend/`, with `VITE_API_BASE=https://<api-domain>/api` at build time.

## Operations
- Liveness: `GET /api/livez` (no dependencies). Readiness: `GET /api/health` (database reachable).
- Every response carries `X-Request-ID`, which is also in the JSON log line, so you can trace a user
  report to the exact request.
- Cache: `GET /api/cache/stats` gives in-process hit and miss counts. Bump `ENGINE_VERSION` in
  `app/cache.py` whenever solver behaviour changes.
- Database growth: `shift_events` and `plan_cache` are append-only. Prune old rows with a scheduled job
  (for example Supabase `pg_cron`: delete `plan_cache` rows older than 30 days).
