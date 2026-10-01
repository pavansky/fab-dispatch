# Security

## Threat model (scope of this build)

A planning tool for one site's engineering team. It handles operational data (tool IDs, shift plans)
and no personal or financial data. Engineer names are synthetic.

| Threat | Mitigation |
|---|---|
| Oversized or expensive requests (DoS) | Pydantic limits on every input (≤ 60 engineers, ≤ 200 jobs, ≤ 30 benchmark seeds, ≤ 500-char symptoms). Per-client token-bucket rate limits on `/plan`, `/benchmark`, `/optimality-gap`, live writes and repair search. Solver iteration and time caps. Explicit 413 for oversized scenarios. |
| SQL injection | Parameterised queries only (sqlite3 and psycopg placeholders). No string-built SQL from input. |
| Lost updates between dispatchers | Optimistic versioning on live shifts. `If-Match` gives 409 instead of a silent overwrite. |
| Information leakage | One error envelope with no stack traces. Public `/api/health` reports only status, db_ok and version. |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` on every response. |
| Cross-origin abuse | CORS allow-list from settings (same origin in production). |
| Secrets in the repo | None needed locally. Production secrets live only in platform environment variables; see `.env.example`. |
| Container hardening | Non-root user (uid 10001), slim base, no build tools in the runtime image. |

## Not in scope (and what production would add)

- **Authentication and authorisation.** All endpoints are open, which is right for an assessment demo.
  A real deployment would put SSO (OIDC) in front and add roles: a viewer can watch live shifts, a
  dispatcher can advance and report.
- **Audit trail.** `shift_events` already records every change with the request's time. Adding the
  acting user to each event would make it a full audit log.
- **Edge rate limiting.** In-process limits are per instance; a WAF or edge rules should own this in
  production.

## Reporting

Please report vulnerabilities privately to the maintainer rather than opening a public issue.
