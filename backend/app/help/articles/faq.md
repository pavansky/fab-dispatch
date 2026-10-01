---
title: FAQ and troubleshooting
summary: Common questions and what to do when something looks wrong.
section: Reference
order: 6
keywords: [faq, question, problem, issue, trouble, troubleshooting, error, broken, not working, slow, stuck, solving, cache, cached, offline, reconnecting, disabled, unassigned, same result, deterministic, data, real data, synthetic]
---

# FAQ and troubleshooting

## Why are some jobs unassigned?

No engineer could do them within the hard rules: not certified, level too low, at max jobs, can't
arrive in the window, or would overrun the shift. Click the job on the floor plan to see the reason
for each strategy. If every strategy leaves the same work unserved, check **Workforce**: you're
short of certified engineers.

## Why do strategies give different plans for the same shift?

They decide in different orders and search to different depths. They all obey the same constraints
and share one cost function, so their costs are directly comparable.

## Why is a slower strategy recommended?

Only when its plan is cheaper by more than the noise margin. See
[How the recommendation works](help:recommendation).

## Results look identical after I changed something

Plans are cached by their exact inputs, so returning to an earlier setting is instant. Changing any
weight, engineer or job always re-solves.

## "Solving…" doesn't finish

The search strategies stop within a few seconds. If a strategy reports an error, check your
connection; the other strategies' results stay on screen.

## A button is greyed out

Starting live shifts and running benchmarks need the **dispatcher** role. See
[Accounts, roles and access](help:roles-and-access).

## Live view says "reconnecting"

The connection dropped. It catches up automatically, without missing events, once you're back online.

## Is this real fab data?

No. Floors, faults, skills and repair histories are synthetic but realistic, and seeded so results
are reproducible.
