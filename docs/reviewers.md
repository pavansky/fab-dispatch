# Review it in 10 minutes

A guided path through the product and the engineering, for anyone evaluating the project.

## The app in 5 minutes

Open the [live app](https://fab-dispatch.vercel.app) and click **Try it as a guest**.

1. **Overview.** Five strategies solve the same shift in parallel. Read the recommendation card: it
   names the plan *and* why, and refuses to call a difference inside the noise margin a win.
2. **Floor plan.** Click a job marked **×** (unassigned). The inspector shows, per strategy, who was
   chosen or why nobody could be: *4 not certified, 1 at max jobs*.
3. **Drag a cost weight** in the left panel. Every strategy re-solves; repeat plans come from cache.
4. **Ask the assistant** (bottom right, or **/**): *"Why is J006 assigned this way?"* The answer
   matches the inspector exactly and cites its sources. Then ask *"What's the weather in Paris?"*:
   it says it doesn't know.
5. **Live dispatch.** Start a live shift, press **+1 h**, then turn on *Tap floor to report a
   bottleneck down* and click the floor. Open **Copy link** in a second window: both update live.
6. **Benchmark.** Run it: strategies compared over many shifts with 95% confidence intervals, and
   each heuristic's gap to the proven optimum.

## The engineering in 5 minutes

| Look at | Why it matters |
|---|---|
| [Requirements map](https://github.com/pavansky/fab-dispatch#requirements-map) | Every item in the brief, where it lives in the app and the code. |
| [Analysis](ANALYSIS.md) | What comparing the algorithms taught: when each one wins, and why. |
| [Decisions](DECISIONS.md) | 32 design decisions with context and trade-offs. |
| [`planner.py`](https://github.com/pavansky/fab-dispatch/blob/main/backend/app/planner.py) | The constraint engine every strategy shares: the reason the comparison is fair. |
| [`algorithms/`](https://github.com/pavansky/fab-dispatch/tree/main/backend/app/algorithms) | Greedy, Hungarian, Regret-2, ALNS, PyVRP and the exact MILP. |
| [AI transparency](ai.md) | How the assistant stays grounded, and how its quality is measured. |
| [CI](https://github.com/pavansky/fab-dispatch/actions) | Lint, three test layers, coverage floors, audits, accessibility, image builds. |
| [Changelog](project/changelog.md) | Versioned releases, including the security fix found in production. |

## By the numbers

- **5** strategies plus an exact optimum, on **2** fabs with different floors, shifts and bottlenecks
- **446** automated tests across pytest, Vitest and Playwright (desktop and phone, with WCAG checks)
- **42 / 42** assistant evaluation questions cite the right article; **8 / 8** off-topic refused
- **Every deploy** smoke-tested: health, schema, real auth, and app tables closed to the public API

## Things worth noticing

- **It refuses false positives.** One shift is noise: a 1% cost "win" is called a tie (see
  [how it decides](guide/recommendation.md)).
- **The tests found real bugs:** a blank screen when rejoining a live shift, a phone layout wider than
  the screen, and an emailed code the sign-in screen couldn't accept. Each has a regression test.
- **A real production incident, handled:** Supabase exposed app tables through its public API by
  default. It was found, fixed with a migration, and is now checked after every deploy
  ([v2.0.3](project/changelog.md)).
