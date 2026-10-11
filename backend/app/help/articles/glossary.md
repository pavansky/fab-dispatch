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

**Response window.** When work may start: from when the job is reported to its latest start. The
widths come from the fab profile's preset (for example 45 min for a bottleneck down and 120 for a
tool-down in Fab 1's normal shift, 40 and 120 in Fab 2's, 25 and 60 in an excursion); PMs get 240.

**Certification and level.** An engineer is certified per tool family at level 1 (basic) to 3
(expert). A job needs a minimum level.

**Home bay.** Where an engineer starts the shift.

**Aisle distance.** Walking along the fab's grid of aisles (along, then across), not in a straight
line.

**Tool family.** A group of tools of one kind, such as Etch or CMP, in its own area of the floor.

**Excursion.** In a fab, a process or yield deviation (an SPC excursion) handled by lot holds and
an out-of-control action plan, not by maintenance dispatch. In this app, *Excursion / surge* is a
preset that models a surge of unplanned tool-downs with tight response targets.

**Wafer moves.** Wafer-steps processed per period, a throughput activity metric. The fab's output is
measured in wafers (or good die) out; a down bottleneck tool costs moves now and output later.

**Fab profile.** The data describing one fab: floor, tool families, faults, shift pattern and
presets. See [Fabs and profiles](help:fabs).
