---
title: Glossary
summary: Fab and dispatch terms used in the app.
section: Reference
order: 2
keywords: [glossary, term, terms, define, definition, meaning, what is, what does, mean, tool-down, tool down, pm, preventive maintenance, bottleneck, constraint tool, certification, level, home bay, bay, aisle, wafer moves, fab, cleanroom, excursion, sla, response window, shift, priority]
---

# Glossary

**Tool-down.** An unplanned failure that stops a process tool. It has a response window: the
engineer must start within it.

**Bottleneck down.** A tool-down on the fab's bottleneck (constraint) tool family, usually
lithography. Priority 3. Every minute it's down costs wafer moves for the whole fab.

**PM (preventive maintenance).** Planned work with a wider window. Priority 1.

**Priority.** 3 = bottleneck down, 2 = other tool-down, 1 = PM.

**Response window.** When work may start: from when the job is reported to its latest start (45 min
for a bottleneck down, 120 for a tool-down, 240 for a PM, by default).

**Certification and level.** An engineer is certified per tool family at level 1 (basic) to 3
(expert). A job needs a minimum level.

**Home bay.** Where an engineer starts the shift.

**Aisle distance.** Walking along the fab's grid of aisles (along, then across), not in a straight
line.

**Tool family.** A group of tools of one kind, such as Etch or CMP, in its own area of the floor.

**Excursion.** A process problem that triggers a surge of tool-downs.

**Wafer moves.** Wafers processed through a step; the fab's output measure.

**Fab profile.** The data describing one fab: floor, tool families, faults, shift pattern and
presets. See [Fabs and profiles](help:fabs).
