---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

![Fab Dispatch](assets/favicon.svg){ .hero-mark }

# The right engineer to every tool-down, in real time.

Fab Dispatch assigns equipment engineers to tool-downs and preventive maintenance in a
semiconductor fab. It solves every shift with **five allocation strategies**, from a one-pass greedy
to a state-of-the-art vehicle-routing solver, recommends one with a rule that refuses false
positives, explains every decision, and runs the shift **live** for a whole team.

[Try it now: one click, no sign-up :material-arrow-right:](https://fab-dispatch.vercel.app){ .md-button .md-button--primary }
[Run it locally](quickstart.md){ .md-button }
[Review it in 10 minutes](reviewers.md){ .md-button }

</div>

## Three ways to try it

| | How | Time |
|---|---|---|
| **Live** | Open [fab-dispatch.vercel.app](https://fab-dispatch.vercel.app) and click **Try it as a guest**. | 10 seconds |
| **In your browser** | [Open in GitHub Codespaces](https://codespaces.new/pavansky/fab-dispatch?quickstart=1): it installs and starts everything. | ~3 minutes |
| **On your machine** | `git clone https://github.com/pavansky/fab-dispatch && cd fab-dispatch && python3 run.py` | ~3 minutes |

No accounts, API keys or paid services are needed to run it locally.

## What's inside

<div class="grid cards" markdown>

-   :material-strategy:{ .lg } **Five strategies, one engine**

    Greedy, Hungarian, Regret-2, ALNS and PyVRP share one constraint engine and cost function, so
    comparisons are fair. An exact MILP proves how far each heuristic is from the optimum.
    [Strategies](guide/strategies.md) · [Analysis](ANALYSIS.md)

-   :material-scale-balance:{ .lg } **Recommendations without false positives**

    Cost differences inside a noise margin are ties, never wins; the benchmark uses paired
    bootstrap confidence intervals. [How it decides](guide/recommendation.md)

-   :material-map-marker-path:{ .lg } **Every decision explained**

    For any job: who was chosen, the next best, why others were rejected, the cost breakdown, and a
    repair-history prediction from Qdrant. [Floor plan](guide/floor-plan.md)

-   :material-broadcast:{ .lg } **Live dispatch for a team**

    Tool-downs arrive as the clock runs; the plan re-optimises in under a second without reshuffling
    people, and every screen updates over Server-Sent Events. [Live dispatch](guide/live-dispatch.md)

-   :material-robot-happy-outline:{ .lg } **A grounded assistant**

    Answers about the shift on screen and the app, always with sources, and says "I don't know"
    rather than guess. Measured on an evaluation set in CI. [How it works](ai.md)

-   :material-factory:{ .lg } **Any fab, no code changes**

    Floor, tool families, faults, shifts and presets live in a validated JSON profile; two fabs ship.
    [Onboard a fab](ONBOARDING_A_FAB.md)

-   :material-shield-check:{ .lg } **Secure and multi-tenant**

    Supabase Auth, roles, per-fab access, CAPTCHA, row-level security, strict CSP, and a smoke test
    after every deploy. [Security](project/security.md)

-   :material-test-tube:{ .lg } **Tested at every layer**

    Backend, component and end-to-end tests (desktop and phone) in CI, with coverage floors and
    accessibility checks. [Contributing](project/contributing.md)

</div>

## Built with

React 19 · Vite · FastAPI · PyVRP · SciPy (HiGHS) · NumPy · Qdrant · Supabase (Postgres, Auth) ·
Vercel · Cloudflare Turnstile · Playwright · Vitest · pytest · GitHub Actions
