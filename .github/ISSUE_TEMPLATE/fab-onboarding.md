---
name: Onboard a new fab
about: Add a site profile so a new fab can use the dispatcher
labels: onboarding
---
**Fab**: name, id (e.g. `fab3-300mm-memory`), node / wafer size

**Floor plan**: width × height in metres, and the bay rectangle of each tool family

**Tool families**: id, label, tool-ID prefix, which one is the constraint (bottleneck)

**Shift pattern**: start hour, length in minutes

**Fault catalogue**: per family, fault codes with typical symptoms, root causes and repair times

**Users**: who are dispatchers and viewers (emails), so access can be scoped to this fab

See `docs/ONBOARDING_A_FAB.md`.
