"""The recommendation rule, server side.

A mirror of ``frontend/src/lib/analysis.js`` (``recommendValue`` / ``recommendGoal``), so the
assistant can explain a recommendation from the plans themselves instead of echoing prose the
browser sent. Keep the two in step: the rule is the product's promise ("never declares a winner
on a difference that could be noise"), and the help article describes it step by step.

* **Best value**: guard (never give up bottleneck coverage, nor priority-weighted coverage when
  some plan leads on both), cheapest of what's left, every plan within the noise margin of it is
  a tie, the fastest to compute among the ties wins.
* **Other goals**: lexicographic ranking on the goal's metrics with a tie tolerance, anchored on
  the best value of each key so it's transitive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALGO_ORDER = ["greedy", "hungarian", "regret", "alns", "pyvrp"]
ALGO_NAMES = {"greedy": "Greedy", "hungarian": "Hungarian", "regret": "Regret-2", "alns": "ALNS", "pyvrp": "PyVRP"}

GOALS = {
    "value": {"label": "Best value: cost × latency", "rank": ["objective", "runtime_ms"]},
    "bottleneck": {
        "label": "Protect bottleneck tools",
        "rank": ["critical_coverage_pct", "mean_response_min", "priority_weighted_coverage_pct"],
    },
    "coverage": {"label": "Maximise coverage", "rank": ["priority_weighted_coverage_pct", "coverage_pct", "objective"]},
    "cost": {"label": "Lowest total cost", "rank": ["objective", "priority_weighted_coverage_pct"]},
}
LABELS = {
    "objective": "total cost",
    "runtime_ms": "solve time",
    "critical_coverage_pct": "bottleneck downs covered",
    "mean_response_min": "response to tool-downs",
    "priority_weighted_coverage_pct": "priority-weighted coverage",
    "coverage_pct": "jobs covered",
    "wait_min_total": "idle wait",
}
UNITS = {
    "objective": "pts",
    "runtime_ms": "ms",
    "critical_coverage_pct": "%",
    "mean_response_min": "min",
    "priority_weighted_coverage_pct": "%",
    "coverage_pct": "%",
    "wait_min_total": "min",
}
HIGHER_IS_BETTER = {"coverage_pct", "critical_coverage_pct", "priority_weighted_coverage_pct", "utilization_pct"}
# Differences smaller than this are treated as a tie when ranking.
TIE = {
    "critical_coverage_pct": 0.05,
    "priority_weighted_coverage_pct": 0.05,
    "coverage_pct": 0.05,
    "mean_response_min": 0.25,
    "objective": 0.5,
}


def fmt(v: float, digits: int = 1) -> str:
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.{digits}f}"


def ms(v: float) -> str:
    return f"{fmt(v, 1 if v < 10 else 0)} ms"


def value(key: str, v: float) -> str:
    unit = UNITS.get(key, "")
    return f"{fmt(v)}{unit}" if unit == "%" else f"{fmt(v)} {unit}".rstrip()


def cost_margin(cheapest: float) -> float:
    """Cost differences smaller than this are noise, not a win (2% of the cheapest, at least 5)."""
    return max(0.02 * abs(cheapest), 5.0)


def improvement(key: str, v: float, base: float) -> float:
    """Signed improvement of ``v`` over ``base``: positive is always better."""
    d = v - base
    return d if key in HIGHER_IS_BETTER else -d


@dataclass
class Recommendation:
    goal: str
    winner: str
    why: str
    tradeoff: list[str] = field(default_factory=list)
    ranked: list[str] = field(default_factory=list)
    pool: list[str] = field(default_factory=list)
    near_tie: list[str] = field(default_factory=list)
    margin: float | None = None

    @property
    def goal_label(self) -> str:
        return GOALS[self.goal]["label"]


def _order(a: str) -> int:
    return ALGO_ORDER.index(a) if a in ALGO_ORDER else len(ALGO_ORDER)


def _names(algos: list[str]) -> str:
    names = [ALGO_NAMES.get(a, a) for a in algos]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _speedup(fast: float, slow: float) -> str | None:
    ratio = slow / max(fast, 0.1)
    if slow - fast < 5 or ratio < 1.25:
        return None
    if ratio >= 2:
        return f"{fmt(round(ratio) if ratio >= 10 else round(ratio * 10) / 10)}× faster"
    return f"{fmt(round(slow - fast))} ms faster"


def _recommend_value(metrics: dict[str, dict[str, float]]) -> Recommendation:
    algos = sorted(metrics, key=_order)
    crit = {a: metrics[a]["critical_coverage_pct"] for a in algos}
    pri = {a: metrics[a]["priority_weighted_coverage_pct"] for a in algos}
    cost = {a: metrics[a]["objective"] for a in algos}
    time = {a: metrics[a]["runtime_ms"] for a in algos}

    def by_cost(a):
        return (cost[a], _order(a))

    # 1. Guard: never give up bottleneck coverage, nor (when some plan leads on both)
    #    priority-weighted coverage, for speed or cost.
    best_crit, best_pri = max(crit.values()), max(pri.values())
    crit_safe = [a for a in algos if crit[a] >= best_crit - 1e-9]
    both = [a for a in crit_safe if pri[a] >= best_pri - 0.5]
    bottleneck_only = not both
    pool = crit_safe if bottleneck_only else both
    # 2. Cheapest plan, and everything within the noise margin of it.
    by_cost_sorted = sorted(pool, key=by_cost)
    cheapest = by_cost_sorted[0]
    margin = cost_margin(cost[cheapest])
    near_tie = [a for a in pool if cost[a] <= cost[cheapest] + margin]
    # 3. Among statistically indistinguishable plans, the fastest wins.
    by_time = sorted(near_tie, key=lambda a: (time[a], *by_cost(a)))
    winner = by_time[0]
    ranked = [winner] + sorted((a for a in algos if a != winner), key=by_cost)
    m = metrics[winner]
    excluded = [a for a in algos if a not in pool]
    short = ALGO_NAMES.get

    if len(pool) == 1:
        if len(algos) == 1:
            why = "Only strategy with a plan."
        else:
            why = (
                f"Only strategy that keeps the best bottleneck coverage ({fmt(best_crit)}% of bottleneck downs)"
                f"{'' if bottleneck_only else ' and priority-weighted coverage'}."
            )
    elif winner == cheapest and len(near_tie) == 1:
        nxt = by_cost_sorted[1]
        gap = cost[nxt] - cost[winner]
        fastest = sorted(pool, key=lambda a: (time[a], *by_cost(a)))[0]
        pct = round(100 * gap / (cost[nxt] or 1))
        why = (
            f"Cheapest plan by a real margin: {fmt(cost[winner])} pts, {fmt(gap)} pts ({pct}%) below "
            f"{short(nxt, nxt)}, more than the {fmt(margin, 0)}-pt noise margin."
        )
        why += (
            f" It's also the fastest to compute ({ms(time[winner])})."
            if fastest == winner
            else f" That saving is worth its {ms(time[winner])} solve."
        )
    elif winner == cheapest:
        nxt = by_time[1]
        sp = _speedup(time[winner], time[nxt])
        why = (
            f"Cheapest plan ({fmt(cost[winner])} pts), and the fastest of {len(near_tie)} equivalent plans "
            f"within the {fmt(margin, 0)}-pt noise margin: "
        )
        why += (
            f"{sp} than {short(nxt, nxt)} ({ms(time[winner])} vs {ms(time[nxt])})."
            if sp
            else f"{ms(time[winner])}, about as fast as {short(nxt, nxt)} ({ms(time[nxt])})."
        )
    else:
        diff = cost[winner] - cost[cheapest]
        if diff < 0.05:
            cost_part = (
                f"{short(winner, winner)} and {short(cheapest, cheapest)} cost the same ({fmt(cost[winner])} pts)."
            )
        else:
            cost_part = (
                f"{short(cheapest, cheapest)} is cheaper by only {fmt(diff)} pts, inside the {fmt(margin, 0)}-pt "
                "noise margin, so it isn't a real win."
            )
        sp = _speedup(time[winner], time[cheapest])
        speed_part = (
            f"{short(winner, winner)} gets an equivalent plan {sp} ({ms(time[winner])} vs {ms(time[cheapest])})."
            if sp
            else (
                f"{short(winner, winner)} is the fastest of {len(near_tie)} equivalent plans, though only just "
                f"({ms(time[winner])} vs {ms(time[cheapest])})."
            )
        )
        why = f"{cost_part} {speed_part}"
    jobs = int(m.get("jobs", 0))
    why += f" Covers {fmt(m.get('assigned', 0))} of {jobs} job{'s' if jobs != 1 else ''}, "
    why += f"{fmt(m['critical_coverage_pct'])}% of bottleneck downs."
    if bottleneck_only:
        why += " No plan leads on both bottleneck and priority-weighted coverage, so bottleneck coverage alone set the shortlist."

    tradeoff = []
    if excluded:
        what = "bottleneck" if bottleneck_only else "bottleneck or priority-weighted"
        tradeoff.append(f"Not considered, less {what} coverage: {_names(excluded)}")
    faster = sorted((a for a in pool if time[a] < time[winner] and a not in near_tie), key=by_cost)
    if faster:
        f = faster[0]
        tradeoff.append(f"{short(f, f)} answers in {ms(time[f])} but costs {fmt(cost[f] - cost[winner])} pts more")
    return Recommendation("value", winner, why, tradeoff, ranked, pool, near_tie, margin)


def _leaders(items: list[str], metrics: dict, key: str) -> list[str]:
    """Items within the tie tolerance of the best one on ``key`` (anchored on the best)."""
    best = items[0]
    for a in items[1:]:
        if improvement(key, metrics[a][key], metrics[best][key]) > 0:
            best = a
    tol = TIE.get(key, 0)
    return [a for a in items if a == best or improvement(key, metrics[best][key], metrics[a][key]) <= tol]


def rank_by(items: list[str], metrics: dict, keys: list[str]) -> list[str]:
    items = sorted(items, key=_order)
    if len(items) <= 1 or not keys:
        return items
    key, rest = keys[0], keys[1:]
    out: list[str] = []
    left = items
    while left:
        group = _leaders(left, metrics, key)
        out += rank_by(group, metrics, rest)
        left = [a for a in left if a not in group]
    return out


def _recommend_goal(metrics: dict[str, dict[str, float]], goal: str) -> Recommendation:
    rank = GOALS[goal]["rank"]
    algos = list(metrics)
    ranked = rank_by(algos, metrics, rank)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    lead = rank[0]
    m = metrics[winner]
    short = ALGO_NAMES.get
    if not runner_up:
        why = "Only strategy with a plan."
    else:
        group, split_key = algos, None
        for key in rank:
            group = _leaders(group, metrics, key)
            if runner_up not in group:
                split_key = key
                break
        if split_key == lead:
            gap = abs(m[lead] - metrics[runner_up][lead])
            why = (
                f"Best {LABELS[lead]}: {value(lead, m[lead])}, {value(lead, gap)} ahead of "
                f"{short(runner_up, runner_up)}, the next best."
            )
        elif split_key:
            tied = [a for a in _leaders(algos, metrics, lead) if a != winner]
            why = (
                f"Ties with {_names(tied)} on {LABELS[lead]} ({value(lead, m[lead])}) and wins on "
                f"{LABELS[split_key]}: {value(split_key, m[split_key])} vs "
                f"{value(split_key, metrics[runner_up][split_key])} for {short(runner_up, runner_up)}."
            )
        elif len(group) == len(algos):
            why = f"All {len(algos)} strategies tie on this goal, so {short(winner, winner)} is listed first by default order."
        else:
            others = [a for a in group if a != winner]
            why = f"Ties with {_names(others)} on every criterion of this goal; listed first by default order."
    jobs = int(m.get("jobs", 0))
    why += f" Covers {fmt(m.get('assigned', 0))} of {jobs} job{'s' if jobs != 1 else ''}."

    tradeoffs = []
    for key in ["coverage_pct", "critical_coverage_pct", "mean_response_min", "wait_min_total", "objective"]:
        if key == lead or key not in m:
            continue
        best = None
        for a in algos:
            if a == winner or key not in metrics[a]:
                continue
            gain = improvement(key, metrics[a][key], m[key])
            if gain > TIE.get(key, 0.5) and (best is None or gain > best[1]):
                best = (a, gain)
        if best:
            tradeoffs.append((key, best[0], best[1], abs(best[1]) / (abs(m[key]) or 1)))
    tradeoffs.sort(key=lambda t: -t[3])
    tradeoff = [
        f"{short(a, a)} is {value(key, gain)} {'higher' if key in HIGHER_IS_BETTER else 'lower'} on {LABELS[key]}"
        for key, a, gain, _ in tradeoffs[:2]
    ]
    return Recommendation(goal, winner, why, tradeoff, ranked)


def recommend(metrics: dict[str, dict[str, float]], goal: str = "value") -> Recommendation:
    """The recommended strategy for a planning goal, from each strategy's metrics."""
    if goal not in GOALS:
        raise ValueError(f"unknown planning goal {goal!r}")
    if not metrics:
        raise ValueError("no plans to recommend from")
    return _recommend_value(metrics) if goal == "value" else _recommend_goal(metrics, goal)
