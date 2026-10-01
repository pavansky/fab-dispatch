# Security

## Threat model (scope of this build)

A multi-fab planning and dispatch tool. It handles operational data (tool IDs, shift plans,
dispatcher actions) and user email addresses; no financial data. Engineer names are synthetic.

| Threat | Mitigation |
|---|---|
| Oversized or expensive requests (DoS) | Pydantic limits on every input (≤ 60 engineers, ≤ 200 jobs, ≤ 30 benchmark seeds, ≤ 500-char symptoms). Per-client token-bucket rate limits on `/plan`, `/benchmark`, `/optimality-gap`, live writes and repair search. Solver iteration and time caps. Explicit 413 for oversized scenarios. |
| SQL injection | Parameterised queries only (sqlite3 and psycopg placeholders). No string-built SQL from input. |
| Lost updates between dispatchers | Optimistic versioning on live shifts. `If-Match` gives 409 instead of a silent overwrite. |
| Information leakage | One error envelope with no stack traces. Public `/api/health` reports only status, db_ok, schema_ok, version and environment name. |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` on every response. |
| Cross-origin abuse | CORS allow-list from settings (same origin in production). |
| Secrets in the repo | None needed locally. Production secrets live only in platform environment variables; see `.env.example`. |
| Container hardening | Non-root user (uid 10001), slim base, no build tools in the runtime image. |
| Unauthenticated access | Every endpoint except health, liveness, metadata and auth config requires a bearer token. Supabase tokens are verified against the project's JWKS (or legacy HS256 secret) with issuer and audience checks; demo tokens are refused in production by configuration. |
| Privilege escalation | Roles and fab access come from Supabase `app_metadata` (admin-only), not user-editable claims. Dispatcher-only actions return 403. |
| Bypassing the API through Supabase | App tables have row-level security on with no policies, and the public `anon`/`authenticated` roles have no grants (migration 3), so the publishable key can't reach app data through Supabase's Data API. Only this service, as table owner, can. Checked after every production deploy. |
| Cross-tenant data access | Every fab-scoped request and live shift is checked against the user's fabs, and returns 404 (not 403) outside them. |
| Replay / double-apply | `Idempotency-Key` on mutating live calls; optimistic versioning on shift writes. |
| XSS, clickjacking | Strict Content-Security-Policy (`script-src 'self'`, `frame-ancestors 'none'`), HSTS and Permissions-Policy on the web app (Vercel and nginx). |
| Scheduled job abuse | `/api/internal/prune` requires `CRON_SECRET`, compared in constant time. |
| Guest sign-ins | Supabase anonymous users get `FAB_GUEST_ROLE` only; their tokens can't claim a higher role (role and email claims are ignored for guests); `none` refuses them. Supabase rate-limits anonymous sign-ups per IP, and every API limit applies per guest. |
| Assistant misuse | The assistant only reads (no tool changes anything), answers from the help articles and the caller's own plans, applies the same fab scoping and size limits as `/plan`, caps questions at 500 characters, and is rate-limited per user. The optional LLM sees only the question and the grounded answer, can only reword it, and its output never carries citations or actions; any failure falls back to the grounded answer. |
| Help content | Rendered as React elements (no raw HTML), so Markdown can't inject script under the CSP. Broken internal links fail at startup and in CI. |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI; Dependabot weekly updates. |

## Not in scope (and what production would add)

- **Enterprise SSO.** Supabase Auth supports SAML/OIDC providers; connecting a fab's identity provider
  is configuration, not code.
- **Audit export.** Every live event records its actor and time (`shift_events`); exporting it to the
  customer's SIEM is a natural next step.
- **Edge rate limiting.** In-process limits are per instance; a WAF or edge rules should own this in
  production.

## Reporting

Please report vulnerabilities privately to the maintainer rather than opening a public issue.
