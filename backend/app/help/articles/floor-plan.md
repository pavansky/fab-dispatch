---
title: Reading the floor plan
summary: Marks, routes, coverage changes and the inspector's explanations.
section: Planning
order: 4
keywords: [floor, floor plan, map, spatial, marks, route, routes, legend, inspector, explanation, explain, why, unassigned, assigned, runner-up, next best, rejected, rejection, side by side, coverage changes, select, click]
---

# Reading the floor plan

## The map

- **Squares** are engineers at their home bays, numbered by engineer id.
- **Large circles** are bottleneck tool-downs, **smaller circles** other tool-downs, and **small
  squares** PMs; the legend under the map shows their colours.
- A **×** marks a job the chosen strategy left unassigned.
- **Routes** follow the fab's aisles (along, then across), because bays sit on a grid.
- Hover any job to see its route in focus and the stop order.

Use the buttons above the map to switch strategies, or **Side by side** for all five at once.
**Coverage changes vs Greedy** rings jobs served by this strategy but not by Greedy, or the reverse.

## The inspector

Click a job to open it on the right. For **every strategy** you see:

- **Who was chosen**, and when they start,
- **Why:** the decision rule, the cost, and the **next-best engineer** (or that there was none),
- **Who was rejected and why:** counted reasons such as *not certified*, *certification too low*,
  *at max jobs*, *can't arrive in window*, *would overrun shift*,
- The **cost breakdown:** walking, waiting, over-qualification, workload and priority.

For tool-downs, **Repair history** predicts how long the repair will take from similar past faults,
the likely cause, and who has fixed it before.

Click an engineer to see their route in order, their certifications and how busy they are.

## Keyboard

Jobs and engineers are buttons: **Tab** to them and press **Enter** to inspect.
