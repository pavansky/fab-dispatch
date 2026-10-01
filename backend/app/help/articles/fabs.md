---
title: Fabs and profiles
summary: Switching fabs, what a fab profile contains, and adding a new fab.
section: Reference
order: 4
keywords: [fab, fabs, site, switch fab, change fab, fab 1, fab 2, 300mm, 200mm, profile, profiles, families, tool families, floor, shift pattern, shift length, start hour, new fab, add a fab, onboard, onboarding]
---

# Fabs and profiles

## Switching fab

Choose a fab in the **picker in the top bar**. Everything site-specific switches with it: the floor,
tool families, fault catalogue, shift times and presets. The app remembers your last fab.

Two fabs ship today:

- **Fab 1 · 300mm logic:** 12-hour shifts from 07:00, lithography as the bottleneck.
- **Fab 2 · 200mm analog & power:** 8-hour shifts from 06:00, photolithography as the bottleneck.

## What a fab profile holds

A fab is described by a validated JSON profile: the floor size, each tool family's area and tool-ID
prefix, its fault catalogue (symptoms, causes, repair times), the shift pattern, which family is
the bottleneck, and the planning presets. The engine and the UI read everything from it.

## Adding a fab

Adding a fab is a new profile file, not code. The project's onboarding guide walks through writing,
validating and releasing one, and granting users access to it.
