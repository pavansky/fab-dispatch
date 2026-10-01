"""The assistant: answers questions about the app and the shift on screen.

A small, grounded agent. It never invents facts:

1. **Understand** the question: pull out job ids, engineer ids, strategy names, and the
   intent (a job, an engineer, the recommendation, a comparison, unserved work, or how the
   app works).
2. **Act** with tools that read real data: the plans for the shift on screen (from the same
   cached planning service the UI uses) and the help center (retrieval over the articles).
3. **Answer** from what the tools returned, with citations and follow-up actions. If no tool
   supports an answer (low retrieval score, unknown id), it says so instead of guessing.

An LLM can optionally rewrite the final text (``llm.py``), but only from these grounded facts.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..algorithms import ALGORITHMS
from ..fabs import FabProfile
from ..models import AllocationResult, Scenario, Weights
from .index import HelpIndex, Hit

ALGO_ORDER = ["greedy", "hungarian", "regret", "alns", "pyvrp"]
ALGO_NAMES = {"greedy": "Greedy", "hungarian": "Hungarian", "regret": "Regret-2", "alns": "ALNS", "pyvrp": "PyVRP"}
ALIASES = {
    "greedy": "greedy",
    "hungarian": "hungarian",
    "kuhn": "hungarian",
    "munkres": "hungarian",
    "regret": "regret",
    "regret-2": "regret",
    "regret2": "regret",
    "alns": "alns",
    "neighbourhood": "alns",
    "neighborhood": "alns",
    "pyvrp": "pyvrp",
    "vrp": "pyvrp",
}
PRIORITY = {3: "bottleneck down", 2: "tool down", 1: "PM"}
REJECTION = {
    "skill_missing": "not certified",
    "level_too_low": "certification too low",
    "at_capacity": "at max jobs",
    "window_missed": "can't arrive in window",
    "shift_overrun": "would overrun shift",
}
# Below this retrieval score, a docs answer would be a guess: say so instead.
MIN_DOC_SCORE = 0.5
MAX_QUESTION = 500


# ----------------------------------------------------------------------------- API models
class AskContext(BaseModel):
    """What the user is looking at. Everything is optional; more context, better answers."""

    fab_id: str | None = None
    scenario: Scenario | None = None
    weights: Weights | None = None
    tab: str | None = None
    active: str | None = Field(None, description="strategy shown on the floor plan")
    selection: dict | None = Field(None, description='{"type": "job"|"engineer", "id": "..."}')
    recommendation: dict | None = Field(None, description="what the UI recommends: algorithm, why, goal")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    context: AskContext = AskContext()


class Citation(BaseModel):
    slug: str
    title: str
    heading: str
    anchor: str = ""


class Action(BaseModel):
    label: str
    kind: Literal["job", "engineer", "tab", "help", "strategy"]
    target: str


class Answer(BaseModel):
    answer: str
    intent: str
    citations: list[Citation] = []
    actions: list[Action] = []
    suggestions: list[str] = []
    grounded: bool = True
    provider: str = "local"


# ----------------------------------------------------------------------------- understanding
def strategies_in(text: str) -> list[str]:
    found = []
    for word in re.findall(r"[a-z0-9-]+", text.lower()):
        algo = ALIASES.get(word)
        if algo and algo not in found:
            found.append(algo)
    return found


def classify(question: str, ctx: AskContext) -> tuple[str, dict]:
    q = question.lower()
    jobs = re.findall(r"\b[jJ]\d{3}\b|\bL\d{3}\b", question)
    engineers = re.findall(r"\b[eE]\d{2}\b", question)
    algos = strategies_in(question)
    ent = {"jobs": [j.upper() for j in jobs], "engineers": [e.upper() for e in engineers], "algos": algos}
    if re.fullmatch(r"\s*(hi|hello|hey|help|what can you do|\?)\s*[!.?]*\s*", q):
        return "greeting", ent
    if ent["jobs"]:
        return "job", ent
    if ent["engineers"]:
        return "engineer", ent
    if re.search(r"\b(this|selected|that) (job|engineer)\b", q) and ctx.selection:
        sel = ctx.selection
        ent["jobs" if sel.get("type") == "job" else "engineers"] = [sel.get("id", "")]
        return sel.get("type", "job"), ent
    if re.search(
        r"recommend|best (plan|strategy|choice)|which (strategy|plan|one)|why (is|was) \w+ (chosen|picked)", q
    ):
        return "recommendation", ent
    if len(algos) >= 2 or (algos and re.search(r"\b(compare|vs|versus|difference|better than|faster than)\b", q)):
        return "compare", ent
    if re.search(r"\b(unassigned|unserved|not (served|covered|assigned)|left over|nobody|no one)\b", q):
        return "unassigned", ent
    return "docs", ent


# ----------------------------------------------------------------------------- helpers
def _clock(minutes: float, profile: FabProfile) -> str:
    total = round(profile.shift.start_hour * 60 + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _family(profile: FabProfile, family_id: str) -> str:
    try:
        return profile.family(family_id).label
    except KeyError:
        return family_id


def _fmt(v: float) -> str:
    return f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _cite(hit: Hit) -> Citation:
    return Citation(**hit.citation())


def _article(index: HelpIndex, slug: str, anchor: str = "") -> Citation:
    a = index.articles[slug]
    heading = next((s.heading for s in a.sections if s.anchor == anchor), a.title)
    return Citation(slug=slug, title=a.title, heading=heading, anchor=anchor)


class Assistant:
    """Stateless per question. ``plan`` is a callable (scenario, weights, algorithm) ->
    AllocationResult, normally the cached PlanningService, so answers match the screen."""

    def __init__(self, index: HelpIndex, plan, profile_for):
        self.index, self._plan, self._profile_for = index, plan, profile_for

    # ------------------------------------------------------------------ entry point
    def ask(self, question: str, ctx: AskContext) -> Answer:
        intent, ent = classify(question, ctx)
        handler = getattr(self, f"_{intent}")
        return handler(question, ctx, ent)

    def _plans(self, ctx: AskContext, algos: list[str] | None = None) -> dict[str, AllocationResult]:
        weights = ctx.weights or Weights()
        return {a: self._plan(ctx.scenario, weights, a) for a in (algos or ALGO_ORDER) if a in ALGORITHMS}

    def _need_shift(self, intent: str) -> Answer:
        return Answer(
            intent=intent,
            answer="I need a shift on screen to answer that. Open the planning workspace, then ask again.",
            citations=[_article(self.index, "getting-started")],
        )

    def _focus(self, ctx: AskContext, ent: dict) -> str:
        return (ent["algos"] or [ctx.active or (ctx.recommendation or {}).get("algorithm") or "pyvrp"])[0]

    # ------------------------------------------------------------------ intents
    def _greeting(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        return Answer(
            intent="greeting",
            answer="I answer questions about **this app** and **the shift on your screen**, using the help "
            "articles and the plans you're looking at. I always show my sources, and I'll tell you when I "
            "don't know.",
            citations=[_article(self.index, "assistant")],
            suggestions=self.suggest(ctx),
        )

    def _job(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        if not ctx.scenario:
            return self._need_shift("job")
        job_id = ent["jobs"][0]
        job = next((j for j in ctx.scenario.jobs if j.id == job_id), None)
        if not job:
            ids = sorted(j.id for j in ctx.scenario.jobs)
            return Answer(
                intent="job",
                answer=f"There's no **{job_id}** in this shift. Its jobs are {ids[0]} to {ids[-1]}.",
                suggestions=[f"Why is {ids[0]} assigned this way?"],
            )
        profile = self._profile_for(ctx.scenario.fab_id)
        focus = ent["algos"] or ALGO_ORDER
        plans = self._plans(ctx, focus)
        head = (
            f"**{job.id}** · {job.tool} · {PRIORITY[job.priority]}, needs {_family(profile, job.skill)} level "
            f"{job.min_level}+ · start window {_clock(job.earliest, profile)}–{_clock(job.latest, profile)} · "
            f"{job.duration} min"
        )
        lines, served_by = [], []
        for algo, r in plans.items():
            a = next((x for x in r.assignments if x.job_id == job.id), None)
            if a:
                served_by.append(algo)
                lines.append(
                    f"- **{ALGO_NAMES[algo]}:** {a.tech_id}, starting {_clock(a.start, profile)}. {a.explanation}"
                )
            else:
                u = next(x for x in r.unassigned if x.job_id == job.id)
                lines.append(f"- **{ALGO_NAMES[algo]}:** unassigned. {u.reason}")
        if len(plans) > 1:
            if not served_by:
                summary = "No strategy could serve it within the hard rules, so this is a staffing limit, not an algorithm one."
            elif len(served_by) == len(plans):
                summary = "Every strategy serves it."
            else:
                names = ", ".join(ALGO_NAMES[a] for a in plans if a not in served_by)
                summary = f"Left unassigned by {names}; the others serve it."
        else:
            summary = ""
        return Answer(
            intent="job",
            answer="\n\n".join(x for x in [head, summary, "\n".join(lines)] if x),
            citations=[
                _article(self.index, "floor-plan", "the-inspector"),
                _article(self.index, "constraints-and-weights", "hard-constraints"),
            ],
            actions=[Action(label=f"Open {job.id} on the floor plan", kind="job", target=job.id)],
        )

    def _engineer(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        if not ctx.scenario:
            return self._need_shift("engineer")
        eng_id = ent["engineers"][0]
        eng = next((e for e in ctx.scenario.engineers if e.id == eng_id), None)
        if not eng:
            ids = sorted(e.id for e in ctx.scenario.engineers)
            return Answer(
                intent="engineer", answer=f"There's no **{eng_id}** on this shift. Engineers are {ids[0]} to {ids[-1]}."
            )
        profile = self._profile_for(ctx.scenario.fab_id)
        algo = self._focus(ctx, ent)
        r = self._plans(ctx, [algo])[algo]
        route = next((x for x in r.routes if x.tech_id == eng.id), None)
        skills = ", ".join(f"{_family(profile, k)} L{v}" for k, v in sorted(eng.skills.items(), key=lambda kv: -kv[1]))
        jobs = {j.id: j for j in ctx.scenario.jobs}
        head = f"**{eng.id} · {eng.name}**: {skills}. Max {eng.max_jobs} jobs."
        if not route or not route.stops:
            body = f"Under **{ALGO_NAMES[algo]}**, {eng.id} has no jobs this shift."
        else:
            stops = "\n".join(
                f"{i}. {_clock(s.start, profile)} **{s.job_id}** {jobs[s.job_id].tool} ({PRIORITY[jobs[s.job_id].priority]})"
                for i, s in enumerate(route.stops, 1)
            )
            busy = sum(s.end - s.start for s in route.stops)
            body = (
                f"Under **{ALGO_NAMES[algo]}**, {eng.id} has {len(route.stops)} of {eng.max_jobs} jobs, walks "
                f"{route.metres:,.0f} m, and is hands-on for {busy / 60:.1f} h:\n\n{stops}"
            )
        return Answer(
            intent="engineer",
            answer=f"{head}\n\n{body}",
            citations=[_article(self.index, "floor-plan", "the-inspector")],
            actions=[Action(label=f"Open {eng.id}", kind="engineer", target=eng.id)],
        )

    def _recommendation(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        cites = [
            _article(self.index, "recommendation", "best-value-step-by-step"),
            _article(self.index, "recommendation", "the-noise-margin"),
        ]
        reco = ctx.recommendation or {}
        if not reco.get("algorithm"):
            hit = self.index.search("how the recommendation works planning goal", k=1, slug="recommendation")[0]
            return Answer(intent="recommendation", answer=hit.text, citations=[_cite(hit)])
        algo = reco["algorithm"]
        answer = f"**{ALGO_NAMES.get(algo, algo)}** is recommended for the goal *{reco.get('goal_label', reco.get('goal', 'best value'))}*. {reco.get('why', '')}"
        if reco.get("tradeoff"):
            answer += f"\n\nTrade-off: {reco['tradeoff']}."
        if ctx.scenario:
            plans = self._plans(ctx)
            answer += "\n\n" + self._table(plans, highlight=algo)
        return Answer(
            intent="recommendation",
            answer=answer,
            citations=cites,
            actions=[
                Action(label=f"Show {ALGO_NAMES.get(algo, algo)} on the floor plan", kind="strategy", target=algo)
            ],
        )

    def _compare(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        algos = ent["algos"]
        sections = []
        for a in algos:
            hit = self.index.search(ALGO_NAMES[a], k=1, slug="strategies")
            if hit:
                sections.append(f"**{ALGO_NAMES[a]}.** {hit[0].text.split(chr(10) + chr(10))[0]}")
        answer = "\n\n".join(sections)
        if ctx.scenario:
            plans = self._plans(ctx, algos if len(algos) >= 2 else None)
            answer += "\n\nOn this shift:\n\n" + self._table(plans)
        return Answer(
            intent="compare",
            answer=answer or "Name two strategies to compare, for example *Greedy vs Hungarian*.",
            citations=[_article(self.index, "strategies", "when-each-one-wins"), _article(self.index, "metrics")],
            actions=[Action(label="Open the benchmark", kind="tab", target="benchmark")],
        )

    def _unassigned(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        if not ctx.scenario:
            hit = self.index.search("why are some jobs unassigned", k=1, slug="faq")[0]
            return Answer(intent="unassigned", answer=hit.text, citations=[_cite(hit)])
        algo = self._focus(ctx, ent)
        r = self._plans(ctx, [algo])[algo]
        if not r.unassigned:
            answer = f"**{ALGO_NAMES[algo]}** serves every job on this shift."
        else:
            jobs = {j.id: j for j in ctx.scenario.jobs}
            rows = "\n".join(
                f"- **{u.job_id}** ({PRIORITY[jobs[u.job_id].priority]}): {u.reason}" for u in r.unassigned
            )
            answer = (
                f"**{ALGO_NAMES[algo]}** leaves {len(r.unassigned)} of {len(jobs)} jobs unassigned:\n\n{rows}\n\n"
                "If every strategy leaves the same work, the limit is certified staff: check **Workforce**."
            )
        return Answer(
            intent="unassigned",
            answer=answer,
            citations=[_article(self.index, "faq", "why-are-some-jobs-unassigned")],
            actions=[Action(label="Open Workforce", kind="tab", target="workforce")]
            + [Action(label=f"Open {u.job_id}", kind="job", target=u.job_id) for u in r.unassigned[:3]],
        )

    def _docs(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        hits = self.index.search(question, k=3)
        if not hits or hits[0].score < MIN_DOC_SCORE:
            return Answer(
                intent="unknown",
                answer="I don't know that one. I only answer from the help articles and the shift on your screen, "
                "and I couldn't find anything that covers it. Try rephrasing, or browse help.",
                citations=[Citation(**h.citation()) for h in hits[:2]],
                suggestions=self.suggest(ctx),
            )
        best = hits[0]
        text = best.text if len(best.text) < 1400 else best.text[:1400].rsplit("\n", 1)[0] + "\n\n…"
        related = [h for h in hits[1:] if h.score >= MIN_DOC_SCORE and h.slug != best.slug][:1]
        return Answer(
            intent="docs",
            answer=text,
            citations=[_cite(best)] + [_cite(h) for h in related],
            actions=[
                Action(
                    label=f"Read: {best.title}",
                    kind="help",
                    target=f"{best.slug}#{best.anchor}" if best.anchor else best.slug,
                )
            ],
        )

    # ------------------------------------------------------------------ shared
    def _table(self, plans: dict[str, AllocationResult], highlight: str | None = None) -> str:
        cols = [
            ("Jobs %", "coverage_pct"),
            ("Bottleneck %", "critical_coverage_pct"),
            ("Response min", "mean_response_min"),
            ("Idle min", "wait_min_total"),
            ("Cost pts", "objective"),
        ]
        head = "| Strategy | " + " | ".join(c for c, _ in cols) + " |\n|---|" + "---|" * len(cols)
        rows = []
        for a, r in plans.items():
            name = f"**{ALGO_NAMES[a]}**" if a == highlight else ALGO_NAMES[a]
            rows.append(f"| {name} | " + " | ".join(_fmt(float(r.metrics[k])) for _, k in cols) + " |")
        return head + "\n" + "\n".join(rows)

    def suggest(self, ctx: AskContext) -> list[str]:
        out = []
        sel = ctx.selection or {}
        if sel.get("type") == "job":
            out.append(f"Why is {sel['id']} assigned this way?")
        elif sel.get("type") == "engineer":
            out.append(f"What is {sel['id']} doing?")
        if ctx.recommendation and ctx.recommendation.get("algorithm"):
            out.append(f"Why is {ALGO_NAMES.get(ctx.recommendation['algorithm'], 'it')} recommended?")
        if ctx.scenario:
            out.append("Which jobs are unassigned?")
            out.append("Compare Greedy and Hungarian")
        out += ["What does idle wait mean?", "How do I report a tool-down?"]
        return out[:4]
