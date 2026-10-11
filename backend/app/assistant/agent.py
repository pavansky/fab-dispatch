"""The assistant: answers questions about the app and the shift on screen.

A small, grounded agent. It never invents facts:

1. **Understand** the question: pull out job ids, engineer ids, strategy names, and the
   intent (a job, an engineer, a repair duration, the recommendation, a comparison, unserved
   work, or how the app works). Ids are normalised first, so *job 6*, *J6* and *J006* are the
   same job and *E3* is *E03*.
2. **Act** with tools that read real data: the plans for the shift on screen (from the same
   cached planning service the UI uses), the repair history index, and the help center
   (retrieval over the articles).
3. **Answer** from what the tools returned, with citations and follow-up actions. If no tool
   supports an answer (low retrieval score, unknown id, a task the app doesn't do such as
   writing code), it says so instead of guessing.

Nothing the browser sends is echoed as fact: the recommendation is recomputed on the server
from the plans with the same rule as the UI (``recommend.py``), and free text from the shift
(engineer names, symptoms) is cleaned before it enters an answer.

An LLM can optionally rewrite the final text (``llm.py``), but only from these grounded facts.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..algorithms import ALGORITHMS
from ..fabs import FabProfile
from ..models import AllocationResult, Job, Scenario, Weights
from .index import HelpIndex, Hit
from .recommend import ALGO_NAMES, ALGO_ORDER, GOALS, recommend

__all__ = [
    "ALGO_NAMES",
    "ALGO_ORDER",
    "INTENTS",
    "Action",
    "Answer",
    "AskContext",
    "AskRequest",
    "Assistant",
    "Citation",
]

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
# Every intent an answer can carry (feedback is validated against this set).
INTENTS = frozenset(
    {"greeting", "job", "engineer", "duration", "recommendation", "compare", "unassigned", "docs", "unknown"}
)
# Below this retrieval score, a docs answer would be a guess: say so instead.
MIN_DOC_SCORE = 0.5
MAX_QUESTION = 500
MAX_FREE_TEXT = 120  # scenario text (names, symptoms) quoted in an answer

# Help sections the tools cite by anchor. tests/test_assistant.py checks each one exists, so a
# renamed heading fails CI instead of citing a section that isn't there.
ANCHORS = {
    "getting-started": "",
    "assistant": "",
    "metrics": "",
    "floor-plan": "the-inspector",
    "constraints-and-weights": "hard-constraints",
    "recommendation": ("best-value-step-by-step", "the-noise-margin", "planning-goals"),
    "strategies": "when-each-one-wins",
    "faq": "why-are-some-jobs-unassigned",
    "what-ifs": "plan-with-history-predicted-durations",
}

# Ids as people type them: "J006", "j6", "job 6", "job #6"; "E03", "e3", "engineer 3". Live
# jobs reported during a shift use an L prefix.
_JOB_REF = re.compile(r"\b(?:job\s*#?\s*|[jJ])(\d{1,3})\b")
_LIVE_JOB_REF = re.compile(r"\b[lL](\d{3})\b")
_ENGINEER_REF = re.compile(r"\b(?:engineer\s*#?\s*|tech(?:nician)?\s*#?\s*|[eE])(\d{1,2})\b")
_DURATION = re.compile(
    r"how long|take to (?:fix|repair|complete|finish|do)|repair (?:time|duration)|\bduration\b|\bpredict"
    r"|\bestimate|how many minutes|how much time|\bfix time\b"
)
_GREETING = re.compile(r"\s*(hi|hello|hey|help|what can you do|\?)\s*[!.?]*\s*")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# Tasks the app doesn't do. These are refused before retrieval, because they often carry app
# vocabulary ("code for the greedy strategy") that would otherwise retrieve an article.
OFF_TASK = [
    (
        "write code",
        re.compile(
            r"\b(write|generate|create|give|show|produce|make|implement|port|rewrite)\b[^.?!]*"
            r"\b(code|script|program|snippet|function|regex|query|implementation)\b"
            r"|\b(python|javascript|typescript|java|rust|golang|c\+\+|c#|sql|bash)\b[^.?!]*\b(code|script|snippet|version|implementation)\b"
            r"|\b(code|script|snippet)\b[^.?!]*\bin (python|javascript|typescript|java|rust|go|sql|bash)\b"
            r"|\bimplement\b[^.?!]*\bin (python|javascript|typescript|java|rust|go|sql)\b"
        ),
    ),
    (
        "translate",
        re.compile(
            r"\btranslat(?:e|ion|ing)\b|\bin (?:german|french|spanish|italian|chinese|japanese|hindi|korean|dutch|portuguese)\b|\bsay .* in \w+\b"
        ),
    ),
    ("tell jokes or write stories", re.compile(r"\b(joke|jokes|pun|limerick|poem|haiku|song|rap|story|riddle)\b")),
    (
        "book or order things",
        re.compile(
            r"\b(book|reserve|order|call)\b[^.?!]*\b(flight|hotel|table|taxi|cab|uber|ticket|tickets|room|pizza|lunch|dinner|food|coffee)\b"
            r"|\b(flight|hotel|taxi|cab|uber|restaurant)\b"
        ),
    ),
    ("check the weather", re.compile(r"\bweather\b|\bforecast\b|\btemperature\b|\bhumidity\b|\brain(?:ing)?\b")),
    (
        "answer general knowledge",
        re.compile(
            r"\b(stock|share) price\b|\bcapital of\b|\bworld cup\b|\brecipe\b|\bcook(?:ing)?\b|\bwho won\b|\bmovie\b|\bfootball\b"
        ),
    ),
]


# ----------------------------------------------------------------------------- API models
class AskContext(BaseModel):
    """What the user is looking at. Everything is optional; more context, better answers."""

    fab_id: str | None = None
    scenario: Scenario | None = None
    weights: Weights | None = None
    tab: str | None = None
    active: str | None = Field(None, description="strategy shown on the floor plan")
    selection: dict | None = Field(None, description='{"type": "job"|"engineer", "id": "..."}')
    recommendation: dict | None = Field(
        None, description="what the UI recommends: algorithm and goal (checked and recomputed on the server)"
    )


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
    fallback_reason: str | None = Field(
        None, description="why an optional LLM rewrite was not used and the grounded answer is shown instead"
    )


# ----------------------------------------------------------------------------- understanding
def clean(text: str, limit: int = MAX_FREE_TEXT) -> str:
    """Scenario free text (an engineer's name, a symptom) as it may appear in an answer."""
    text = _CONTROL.sub(" ", str(text)).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def strategies_in(text: str) -> list[str]:
    found = []
    for word in re.findall(r"[a-z0-9-]+", text.lower()):
        algo = ALIASES.get(word)
        if algo and algo not in found:
            found.append(algo)
    return found


def job_ids_in(text: str) -> list[str]:
    """Normalised job ids in the order mentioned: "job 6" and "J6" are J006."""
    found: list[str] = []
    for m in _JOB_REF.finditer(text):
        found.append(f"J{int(m.group(1)):03d}")
    for m in _LIVE_JOB_REF.finditer(text):
        found.append(f"L{m.group(1)}")
    return list(dict.fromkeys(found))


def engineer_ids_in(text: str) -> list[str]:
    return list(dict.fromkeys(f"E{int(m.group(1)):02d}" for m in _ENGINEER_REF.finditer(text)))


def off_task(question: str) -> str | None:
    """What a question asks the assistant to do that the app doesn't, or None."""
    q = question.lower()
    for label, pattern in OFF_TASK:
        if pattern.search(q):
            return label
    return None


def classify(question: str, ctx: AskContext) -> tuple[str, dict]:
    q = question.lower()
    ent = {"jobs": job_ids_in(question), "engineers": engineer_ids_in(question), "algos": strategies_in(question)}
    if _GREETING.fullmatch(q):
        return "greeting", ent
    if task := off_task(question):
        ent["task"] = task
        return "offtask", ent
    if re.search(r"\b(this|selected|that) (job|engineer)\b", q) and ctx.selection:
        sel = ctx.selection
        ent["jobs" if sel.get("type") == "job" else "engineers"] = [str(sel.get("id", ""))]
    if ent["jobs"] and _DURATION.search(q):
        return "duration", ent
    if ent["jobs"]:
        return "job", ent
    if ent["engineers"]:
        return "engineer", ent
    if re.search(
        r"recommend|best (plan|strategy|choice)|which (strategy|plan|one)|why (is|was) \w+ (chosen|picked)", q
    ):
        return "recommendation", ent
    if len(ent["algos"]) >= 2 or (
        ent["algos"] and re.search(r"\b(compare|vs|versus|difference|better than|faster than)\b", q)
    ):
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


def _fmt(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _cite(hit: Hit) -> Citation:
    return Citation(**hit.citation())


def _article(index: HelpIndex, slug: str, anchor: str = "") -> Citation:
    a = index.articles[slug]
    heading = next(s.heading for s in a.sections if s.anchor == anchor)  # KeyError-like: a renamed heading fails
    return Citation(slug=slug, title=a.title, heading=heading, anchor=anchor)


def _id_range(ids: list[str]) -> str:
    ids = sorted(ids)
    return ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}"


class Assistant:
    """Stateless per question. ``plan`` is a callable (scenario, weights, algorithm) ->
    AllocationResult, normally the cached PlanningService, so answers match the screen.
    ``repairs`` is a callable (profile, family, symptom, roster) -> the repair index's
    ``similar`` result, for duration questions."""

    def __init__(self, index: HelpIndex, plan, profile_for, repairs=None):
        self.index, self._plan, self._profile_for, self._repairs = index, plan, profile_for, repairs

    # ------------------------------------------------------------------ entry point
    def ask(self, question: str, ctx: AskContext) -> Answer:
        intent, ent = classify(question, ctx)
        handler = getattr(self, f"_{intent}")
        return handler(question, ctx, ent)

    def _plans(self, ctx: AskContext, algos: list[str] | None = None) -> dict[str, AllocationResult]:
        weights = ctx.weights or Weights()
        return {a: self._plan(ctx.scenario, weights, a) for a in (algos or ALGO_ORDER) if a in ALGORITHMS}

    def _need_shift(self, intent: str, ctx: AskContext) -> Answer | None:
        """A graceful answer when there's no shift to read, or it has no jobs or engineers."""
        sc = ctx.scenario
        if sc is None:
            text = "I need a shift on screen to answer that. Open the planning workspace, then ask again."
        elif not sc.jobs and not sc.engineers:
            text = "The shift on screen has no jobs and no engineers yet, so there's nothing to plan. Generate a shift first."
        elif not sc.jobs:
            text = (
                "The shift on screen has no jobs yet, so there's nothing to assign. Generate a shift or report a job."
            )
        elif not sc.engineers:
            text = "The shift on screen has no engineers, so no job can be served. Generate a shift with engineers."
        else:
            return None
        return Answer(intent=intent, answer=text, citations=[_article(self.index, "getting-started")])

    def _focus(self, ctx: AskContext, ent: dict) -> str:
        reco = ctx.recommendation or {}
        claimed = reco.get("algorithm") if reco.get("algorithm") in ALGO_NAMES else None
        active = ctx.active if ctx.active in ALGO_NAMES else None
        return (ent["algos"] or [active or claimed or "pyvrp"])[0]

    def _find_job(self, ctx: AskContext, job_id: str) -> Job | None:
        return next((j for j in ctx.scenario.jobs if j.id == job_id), None)

    def _no_such_job(self, intent: str, ctx: AskContext, job_id: str) -> Answer:
        ids = [j.id for j in ctx.scenario.jobs]
        return Answer(
            intent=intent,
            answer=f"There's no **{job_id}** in this shift. Its jobs are {_id_range(ids)}.",
            suggestions=[f"Why is {sorted(ids)[0]} assigned this way?"],
        )

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

    def _offtask(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        """A task the app doesn't do: say so, and offer what the help center does cover."""
        hits = self.index.search(question, k=2)
        related = [h for h in hits if h.score >= MIN_DOC_SCORE][:1]
        text = (
            f"I can't {ent['task']}: I only answer from the help articles and the shift on your screen, "
            "and I don't run tasks."
        )
        if related:
            h = related[0]
            where = f"{h.title} › {h.heading}" if h.heading != h.title else h.title
            text += f" I can explain **{where}**, though: ask me about it, or open the article."
        return Answer(
            intent="unknown",
            answer=text,
            citations=[_cite(h) for h in related],
            actions=[
                Action(label=f"Read: {h.title}", kind="help", target=f"{h.slug}#{h.anchor}" if h.anchor else h.slug)
                for h in related
            ],
            suggestions=self.suggest(ctx),
        )

    def _job(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        if blocked := self._need_shift("job", ctx):
            return blocked
        job_id = ent["jobs"][0]
        job = self._find_job(ctx, job_id)
        if not job:
            return self._no_such_job("job", ctx, job_id)
        if ent["engineers"]:
            return self._job_and_engineer(ctx, ent, job)
        profile = self._profile_for(ctx.scenario.fab_id)
        focus = ent["algos"] or ALGO_ORDER
        plans = self._plans(ctx, focus)
        head = (
            f"**{job.id}** · {clean(job.tool)} · {PRIORITY[job.priority]}, needs {_family(profile, job.skill)} level "
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

    def _job_and_engineer(self, ctx: AskContext, ent: dict, job: Job) -> Answer:
        """ "Can I move J006 to E03?": whether that engineer could take the job under the hard
        rules, and what the plans actually do with it. The assistant can't move work itself."""
        eng_id = ent["engineers"][0]
        eng = next((e for e in ctx.scenario.engineers if e.id == eng_id), None)
        if not eng:
            ids = [e.id for e in ctx.scenario.engineers]
            return Answer(
                intent="job",
                answer=f"There's no **{eng_id}** on this shift. Engineers are {_id_range(ids)}.",
            )
        profile = self._profile_for(ctx.scenario.fab_id)
        level = eng.skills.get(job.skill)
        family = _family(profile, job.skill)
        if level is None:
            verdict = (
                f"**No:** {eng.id} isn't certified for {family}, which **{job.id}** needs (level {job.min_level}+)."
            )
        elif level < job.min_level:
            verdict = f"**No:** {eng.id} is {family} level {level}, and **{job.id}** needs level {job.min_level}+."
        else:
            verdict = (
                f"**Possibly:** {eng.id} is certified ({family} level {level}, {job.id} needs {job.min_level}+). "
                "Whether they can also arrive inside the window, stay under their max jobs and finish before "
                "the shift ends depends on their other work, which each strategy weighs when it plans."
            )
        plans = self._plans(ctx, ent["algos"] or ALGO_ORDER)
        lines = []
        for algo, r in plans.items():
            a = next((x for x in r.assignments if x.job_id == job.id), None)
            route = next((x for x in r.routes if x.tech_id == eng.id), None)
            load = len(route.stops) if route else 0
            if a and a.tech_id == eng.id:
                lines.append(f"- **{ALGO_NAMES[algo]}:** already sends {eng.id}, starting {_clock(a.start, profile)}.")
            elif a:
                lines.append(
                    f"- **{ALGO_NAMES[algo]}:** sends {a.tech_id} instead; {eng.id} holds {load} of {eng.max_jobs} jobs."
                )
            else:
                u = next(x for x in r.unassigned if x.job_id == job.id)
                lines.append(
                    f"- **{ALGO_NAMES[algo]}:** leaves it unassigned ({u.reason}); {eng.id} holds {load} of {eng.max_jobs} jobs."
                )
        tail = (
            "I only read plans, I can't move work. To change who goes, adjust the cost weights or take an "
            "engineer off shift and every strategy re-plans."
        )
        return Answer(
            intent="job",
            answer="\n\n".join([verdict, "\n".join(lines), tail]),
            citations=[
                _article(self.index, "constraints-and-weights", "hard-constraints"),
                _article(self.index, "floor-plan", "the-inspector"),
            ],
            actions=[
                Action(label=f"Open {job.id} on the floor plan", kind="job", target=job.id),
                Action(label=f"Open {eng.id}", kind="engineer", target=eng.id),
            ],
        )

    def _engineer(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        if blocked := self._need_shift("engineer", ctx):
            return blocked
        eng_id = ent["engineers"][0]
        eng = next((e for e in ctx.scenario.engineers if e.id == eng_id), None)
        if not eng:
            ids = [e.id for e in ctx.scenario.engineers]
            return Answer(
                intent="engineer", answer=f"There's no **{eng_id}** on this shift. Engineers are {_id_range(ids)}."
            )
        profile = self._profile_for(ctx.scenario.fab_id)
        algo = self._focus(ctx, ent)
        r = self._plans(ctx, [algo])[algo]
        route = next((x for x in r.routes if x.tech_id == eng.id), None)
        skills = ", ".join(f"{_family(profile, k)} L{v}" for k, v in sorted(eng.skills.items(), key=lambda kv: -kv[1]))
        jobs = {j.id: j for j in ctx.scenario.jobs}
        head = f"**{eng.id} · {clean(eng.name)}**: {skills}. Max {eng.max_jobs} jobs."
        if not route or not route.stops:
            body = f"Under **{ALGO_NAMES[algo]}**, {eng.id} has no jobs this shift."
        else:
            stops = "\n".join(
                f"{i}. {_clock(s.start, profile)} **{s.job_id}** {clean(jobs[s.job_id].tool)} ({PRIORITY[jobs[s.job_id].priority]})"
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

    def _duration(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        """How long a repair will take: the repair-history prediction for the job's symptom,
        with its range and how close the matches are, next to the planner's standard estimate."""
        if blocked := self._need_shift("duration", ctx):
            return blocked
        job_id = ent["jobs"][0]
        job = self._find_job(ctx, job_id)
        if not job:
            return self._no_such_job("duration", ctx, job_id)
        profile = self._profile_for(ctx.scenario.fab_id)
        cites = [
            _article(self.index, "what-ifs", "plan-with-history-predicted-durations"),
            _article(self.index, "floor-plan", "the-inspector"),
        ]
        actions = [Action(label=f"Open {job.id} on the floor plan", kind="job", target=job.id)]
        head = f"**{job.id}** · {clean(job.tool)} · {PRIORITY[job.priority]} · planned for **{job.duration} min**"
        if job.kind != "down" or not job.symptom:
            what = "a PM with a scheduled duration" if job.kind == "pm" else "a tool-down without a symptom"
            return Answer(
                intent="duration",
                answer=f"{head}.\n\n{job.id} is {what}, so the planner uses that figure as it is. Repair history "
                "predicts durations for tool-downs from their symptom text.",
                citations=cites,
                actions=actions,
            )
        if self._repairs is None:
            return Answer(
                intent="duration",
                answer=f"{head}.\n\nRepair history isn't available here, so I can only give the planner's standard estimate.",
                citations=cites,
                actions=actions,
            )
        found = self._repairs(profile, job.skill, job.symptom, [e.id for e in ctx.scenario.engineers])
        symptom = clean(job.symptom)
        pred = found.get("prediction")
        if not pred:
            text = (
                f"{head}.\n\nSymptom: *{symptom}*. Repair history has **no similar past repair** for this "
                f"symptom ({found.get('reason', 'no match')}), so there's no prediction and the planner keeps "
                f"the standard estimate of {job.duration} min."
            )
            weak = found.get("weak_matches") or []
            if weak:
                text += " The nearest records are only weak matches: " + "; ".join(
                    f"*{clean(w['symptom'])}* ({round(100 * w['score'])}%)" for w in weak[:3]
                )
                text += "."
            return Answer(intent="duration", answer=text, citations=cites, actions=actions)
        label = pred.get("match", "")
        quality = {
            "close": "the matches are close",
            "partial": "the matches are only partial",
        }.get(label, "match quality is unknown")
        delta = pred["minutes"] - job.duration
        versus = (
            "about the same as planned"
            if abs(delta) < 10
            else f"{abs(delta)} min {'longer' if delta > 0 else 'shorter'} than planned"
        )
        text = (
            f"{head}.\n\nSymptom: *{symptom}*. From the {pred['neighbours']} most similar past repairs, repair "
            f"history predicts **{pred['minutes']} min** (p10–p90 {pred['p10']}–{pred['p90']} min, the middle "
            f"80% of those repairs' actual times), {versus}. Confidence: **{label or 'n/a'}** "
            f"(mean similarity {pred['confidence']:.2f}, so {quality}). Likely cause: *{clean(pred['likely_cause'])}* "
            f"({round(100 * pred['cause_share'])}% weighted share of the matches; not a probability)."
        )
        experienced = found.get("experienced_engineers") or []
        if experienced:
            text += " Fixed this before, on this shift: " + ", ".join(f"{e} ({n}×)" for e, n in experienced[:3]) + "."
        text += "\n\nTurn on **Plan with history-predicted durations** to plan with this figure instead."
        return Answer(intent="duration", answer=text, citations=cites, actions=actions)

    def _recommendation(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        cites = [
            _article(self.index, "recommendation", "best-value-step-by-step"),
            _article(self.index, "recommendation", "the-noise-margin"),
        ]
        reco = ctx.recommendation or {}
        # The browser's claim is checked, never echoed: only a known strategy id and goal id count.
        claimed = reco.get("algorithm") if reco.get("algorithm") in ALGO_NAMES else None
        goal = reco.get("goal") if reco.get("goal") in GOALS else "value"
        if blocked := self._need_shift("recommendation", ctx):
            if ctx.scenario is not None:  # a shift with no jobs or engineers: say so
                return blocked
            hit = self.index.search("how the recommendation works planning goal", k=1, slug="recommendation")[0]
            text = hit.text
            if claimed:
                text = (
                    f"Your screen recommends **{ALGO_NAMES[claimed]}** for the goal *{GOALS[goal]['label']}*. "
                    "I need the shift on screen to check that against the plans; here is the rule it follows:\n\n"
                    + text
                )
            return Answer(intent="recommendation", answer=text, citations=[_cite(hit)] + cites[:1])
        plans = self._plans(ctx)
        rec = recommend({a: r.metrics for a, r in plans.items()}, goal)
        name = ALGO_NAMES[rec.winner]
        answer = f"**{name}** is recommended for the goal *{rec.goal_label}*. {rec.why}"
        if rec.tradeoff:
            answer += "\n\nTrade-off: " + "; ".join(rec.tradeoff) + "."
        notes = []
        if claimed and claimed != rec.winner:
            notes.append(
                f"Your screen shows **{ALGO_NAMES[claimed]}** as recommended, but from the plans for this shift the "
                f"rule picks **{name}**. The screen may be provisional (strategies still solving) or solved with "
                "other weights; it updates when every strategy has finished."
            )
        elif reco and not claimed:
            notes.append("I didn't recognise the recommendation your screen sent, so this is computed from the plans.")
        asked = next((a for a in ent["algos"] if a != rec.winner), None)
        if asked and not notes:
            notes.append(
                f"**{ALGO_NAMES[asked]}** isn't the pick for this goal; it is ranked {rec.ranked.index(asked) + 1} of {len(rec.ranked)}."
            )
        if notes:
            answer += "\n\n" + " ".join(notes)
        answer += "\n\n" + self._table(plans, highlight=rec.winner)
        if goal != "value":
            cites = [_article(self.index, "recommendation", "planning-goals")] + cites[1:]
        return Answer(
            intent="recommendation",
            answer=answer,
            citations=cites,
            actions=[Action(label=f"Show {name} on the floor plan", kind="strategy", target=rec.winner)],
        )

    def _compare(self, question: str, ctx: AskContext, ent: dict) -> Answer:
        algos = ent["algos"]
        sections = []
        for a in algos:
            hit = self.index.search(ALGO_NAMES[a], k=1, slug="strategies")
            if hit:
                sections.append(f"**{ALGO_NAMES[a]}.** {hit[0].text.split(chr(10) + chr(10))[0]}")
        answer = "\n\n".join(sections)
        if ctx.scenario and not self._need_shift("compare", ctx):
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
        if blocked := self._need_shift("unassigned", ctx):
            return blocked
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
            rows.append(f"| {name} | " + " | ".join(_fmt(r.metrics[k]) for _, k in cols) + " |")
        return head + "\n" + "\n".join(rows)

    def suggest(self, ctx: AskContext) -> list[str]:
        out = []
        sel = ctx.selection or {}
        if sel.get("type") == "job":
            out.append(f"Why is {sel['id']} assigned this way?")
        elif sel.get("type") == "engineer":
            out.append(f"What is {sel['id']} doing?")
        if ctx.recommendation and ctx.recommendation.get("algorithm") in ALGO_NAMES:
            out.append(f"Why is {ALGO_NAMES[ctx.recommendation['algorithm']]} recommended?")
        if ctx.scenario:
            out.append("Which jobs are unassigned?")
            out.append("Compare Greedy and Hungarian")
        out += ["What does idle wait mean?", "How do I report a tool-down?"]
        return out[:4]
