# Security

## Threat model (scope of this build)

A multi-fab planning and dispatch tool. It handles operational data (tool IDs, shift plans,
dispatcher actions) and user email addresses; no financial data. Engineer names are synthetic.

| Threat | Mitigation |
|---|---|
| Oversized or expensive requests (DoS) | Pydantic limits on every input (≤ 60 engineers, ≤ 200 jobs, ≤ 30 benchmark seeds, ≤ 500-char symptoms). Rate limits in two layers on `/plan`, `/benchmark`, `/optimality-gap`, live writes, the live stream (plus at most 4 open streams per user per instance), repair search, help search and the assistant: a token bucket per instance, then for signed-in users a per-minute counter in the database that holds across instances. Unauthenticated endpoints get the in-memory bucket only (no database write per request). When the shared counter is unreachable, cheap endpoints fail open and the expensive ones (`/benchmark`, `/optimality-gap`, `POST /shifts`, an LLM-backed assistant answer) fail closed with 503 + `Retry-After`. Solver iteration and time caps. Explicit 413 for oversized scenarios. |
| SQL injection | Parameterised queries only (sqlite3 and psycopg placeholders). No string-built SQL from input. |
| Lost updates between dispatchers | Optimistic versioning on live shifts. The UI sends the shift's `ETag` as `If-Match` on every write, so a stale tab gets a 409 instead of silently overwriting; the server retries a lost race only when no `If-Match` was sent. |
| Information leakage | One error envelope with no stack traces. Public `/api/health` reports status, `db_ok`, `schema_ok`, the number of databases (never their names), the engine version, release, commit and environment name; `/api/meta` describes the deployment (versions, algorithms, store kind) but never a tenant. |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` and a `Content-Security-Policy` on every API response (`default-src 'self'; frame-ancestors 'none'`; the `/api/docs` and `/api/redoc` pages get a policy that allows exactly their CDN scripts and styles, with the inline bootstrap pinned by hash). HSTS from the API in production. |
| Cross-origin abuse | CORS allow-list from settings (same origin in production). |
| Secrets in the repo | None needed locally. Production secrets live only in platform environment variables; see `.env.example`. |
| Container hardening | Non-root user (uid 10001), slim base, no build tools in the runtime image. |
| Unauthenticated access | Public, unauthenticated endpoints are exactly: `GET /`, `/api/health`, `/api/livez`, `/api/meta`, `/api/auth/config`, `POST /api/auth/demo` (local demo mode only), `/api/help`, `/api/help/{slug}`, `/api/help/search`, `/api/docs`, `/api/redoc`, `/api/openapi.json`; `/api/internal/prune` takes the cron secret and `/api/ingest/*` a per-fab token. Everything else requires a bearer token. Supabase tokens are verified against the project's JWKS (or legacy HS256 secret) with issuer and audience checks and must carry `exp`, `sub`, `aud` and `iss`; demo tokens are refused in production by configuration. The live stream (`EventSource` can't send headers) authenticates with a 90-second HMAC ticket from `POST /api/shifts/{id}/stream-ticket`, bound to the user and that shift, so no long-lived token appears in a URL or a request log. |
| Privilege escalation | Roles and fab access come from Supabase `app_metadata` (admin-only), not user-editable claims; the `FAB_DISPATCHER_EMAILS` bootstrap grant is withheld when the token marks the email unverified. Dispatcher-only actions return 403. On the hosted demo guests are dispatchers by configuration, so a guest may change only the live shifts it started (403 otherwise); named dispatchers share every shift in their fabs. |
| Bypassing the API through Supabase | App tables are closed to Supabase's public PostgREST Data API: row-level security is on with no policies and the `anon`/`authenticated` grants are revoked (migration 3), so the publishable key can't read them. That is all RLS does here: the app connects as the table owner, to which RLS doesn't apply, so no app query is ever filtered by a policy, and on Neon or SQLite (no PostgREST roles) the migration is a no-op. Checked after every production deploy. |
| Cross-tenant data access | Tenant isolation comes from the API, not the database: every fab-scoped request and live shift is checked against the user's fabs (404, not 403, outside them), every query is scoped by `fab_id`, and a fab can be given its own database (`FAB_TENANT_DATABASES`), as production does for fab 2. |
| Replay / double-apply | `Idempotency-Key` on mutating live calls; optimistic versioning on shift writes. |
| XSS, clickjacking | Content-Security-Policy on the web app (Vercel, nginx from every location, and the Vite preview; a test keeps the three identical): `script-src 'self' https://challenges.cloudflare.com` (no inline or eval'd script; Turnstile is the only external script), `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com` (inline *styles* are allowed because the UI's CSS-in-JS sets them; that permits style injection, not script), `connect-src 'self' https://*.supabase.co wss://*.supabase.co` (the browser talks to Supabase Auth directly; the wildcard covers the project subdomain), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`. HSTS and Permissions-Policy alongside. Help content renders as React elements, never raw HTML. |
| Scheduled job abuse | `/api/internal/prune` requires `CRON_SECRET`, compared in constant time. |
| Session tokens in the browser | supabase-js keeps the access and refresh tokens in `localStorage` (no HttpOnly cookie), so any script that runs on the page could read them; the CSP above exists to keep such scripts out, and the access token is short-lived. The live stream never puts the access token in a URL (it uses the 90-second ticket). |
| Guest sign-ins | Supabase anonymous users get `FAB_GUEST_ROLE` only; their tokens can't claim a higher role (role and email claims are ignored for guests); `none` refuses them. Supabase rate-limits anonymous sign-ups per IP, every API limit applies per guest, and Cloudflare Turnstile CAPTCHA (verified by Supabase Auth) blocks scripted sign-ups and email flooding. |
| Assistant misuse | The assistant only reads (no tool changes anything), answers from the help articles and the caller's own plans, applies the same fab scoping and size limits as `/plan`, caps questions at 500 characters, and is rate-limited per user. The optional LLM sees only the question and the grounded answer, can only reword it, and its output never carries citations or actions; any failure falls back to the grounded answer. |
| Help content | Rendered as React elements (no raw HTML), so Markdown can't inject script under the CSP. Broken internal links fail at startup and in CI. |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI; Dependabot weekly updates. |

## Not in scope (and what production would add)

- **Enterprise SSO.** Supabase Auth supports SAML/OIDC providers; connecting a fab's identity provider
  is configuration, not code.
- **Audit export.** Every live event records its actor and time (`shift_events`); exporting it to the
  customer's SIEM is a natural next step.
- **Edge rate limiting.** The API's limits are a token bucket per instance plus, for signed-in users,
  a per-minute counter shared through the database (see the DoS row). Unauthenticated traffic is
  limited per instance only; a WAF or edge rules should own that in production.

## Reporting

Please report vulnerabilities privately rather than opening a public issue: use GitHub's private
vulnerability reporting for this repository, **Security → Report a vulnerability**
(https://github.com/pavansky/fab-dispatch/security/advisories/new). You should hear back within a
week; fixes ship as a patch release and are noted in the changelog.
