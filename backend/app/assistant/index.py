"""Retrieval over the help center: which section answers this question?

This is **lexical retrieval over hashed n-grams**, not a learned embedding. Each entry is
one article section (or one glossary term: a section made of ``**Term.** definition``
paragraphs is split so a term question returns that term), embedded with the same
dependency-free ``HashEmbedder`` as repair history and stored in qdrant-client's in-memory
mode. The corpus ships with the code (a few dozen sections), so it's rebuilt per process in
milliseconds and never goes stale; it doesn't need the Qdrant server even when repair
history uses one. Every point is fetched and re-scored in Python, which is cheap at this
size and keeps one scoring rule.

Ranking adds to the cosine score a lexical boost: the IDF-weighted share of the question's
terms (after stop words, stemming, app synonyms and phrases) that are the article's declared
keywords, in the section heading or summary, or in the section text, damped when only one
word is shared. Short questions ("idle wait?") carry little vector signal, and keywords are
written by people who know the app. The weights and the assistant's refusal threshold were
set on the evaluation set in ``tests/eval`` (method and numbers in ``docs/ai.md``).
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass

from ..help import Article, Section, load_articles
from ..knowledge import DIM, HashEmbedder

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "do",
    "does",
    "did",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "should",
    "so",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "this",
    "to",
    "us",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "tell",
    "show",
    "explain",
    "mean",
    "means",
    "meaning",
    "just",
    "now",
    "one",
    "some",
    "any",
    "get",
    "got",
    "know",
    "thing",
    "things",
    "up",
    "into",
    "about",
    "all",
    "also",
    "always",
    "really",
    "very",
    "isn",
    "don",
    "doesn",
    "didn",
    "won",
    "wasn",
    "aren",
    "t",
    "s",
    "re",
    "ve",
    "ll",
    "d",
    "m",
}

# Words people use for the same thing in this app (query side only).
SYNONYMS = {
    "change": "switch",
    "swap": "switch",
    "select": "switch",
    "logout": "sign",
    "login": "sign",
    "log": "sign",
    "algorithm": "strategy",
    "algo": "strategy",
    "solver": "strategy",
    "kpi": "metric",
    "idle": "wait",
    "add": "report",
    "breakdown": "tool-down",
    "failure": "tool-down",
    "down": "tool-down",
    "technician": "engineer",
    "tech": "engineer",
    "staff": "engineer",
    "people": "engineer",
    "person": "engineer",
    "crew": "engineer",
    "ill": "sick",
    "unwell": "sick",
    "overloaded": "workload",
    "overload": "workload",
    "mouse": "keyboard",
    "ipad": "tablet",
    "iphone": "phone",
    "android": "phone",
    "pick": "recommend",
    "picked": "recommend",
    "chosen": "recommend",
    "choose": "recommend",
    "bot": "assistant",
    "undo": "restore",
    "revert": "restore",
    "cheaper": "cost",
    "cheapest": "cost",
    "expensive": "cost",
    "map": "floor",
    "reconnect": "reconnecting",
    "remember": "remembers",
}
# Multi-word phrases, mapped before tokenising (the original words stay too).
PHRASES = {
    "making things up": "hallucinate",
    "make things up": "hallucinate",
    "makes things up": "hallucinate",
    "called in sick": "sick off shift",
    "call in sick": "sick off shift",
    "went home": "off shift",
    "get back in": "rejoin",
    "come back": "rejoin remembers",
    "log in": "sign in",
    "logged out": "sign out",
    "all five": "side by side",
    "at once": "side by side",
    "same shift again": "seed",
    "work in progress": "locked",
    "already in progress": "locked",
}


def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]  # dragged -> dragg -> drag
    return w[:-1] if w.endswith("e") and len(w) > 4 else w  # measure / measured -> measur


def terms(text: str, expand: bool = False) -> set[str]:
    text = text.lower()
    if expand:
        text += " " + " ".join(v for k, v in PHRASES.items() if k in text)
    words = [w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text) if w not in STOPWORDS and len(w) > 1]
    words += [part for w in words if "-" in w for part in w.split("-") if part not in STOPWORDS and len(part) > 1]
    if expand:
        words += [SYNONYMS[w] for w in words if w in SYNONYMS]
    return set(words) | {_stem(w) for w in words}


@dataclass(frozen=True)
class Hit:
    slug: str
    title: str
    heading: str
    anchor: str
    text: str
    score: float

    def citation(self) -> dict:
        return {"slug": self.slug, "title": self.title, "heading": self.heading, "anchor": self.anchor}


@dataclass(frozen=True)
class Entry:
    """One retrievable unit: a section, or one term of a glossary-style section."""

    article: Article
    section: Section
    heading: str  # the section heading, or the term
    text: str


_TERM = re.compile(r"^\*\*(?P<term>[^*\n]+?)\.?\*\*\s+", re.M)
MIN_TERMS = 3  # a section with this many "**Term.** definition" paragraphs is a glossary


def entries_for(article: Article) -> list[Entry]:
    """Index entries for an article: its sections, except that a glossary-style section
    becomes one entry per term, so "what is a PM?" retrieves the PM definition, not the
    whole list. The citation still points at the section (its anchor), with the term as the
    heading."""
    out = []
    for s in article.sections:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", s.text) if p.strip()]
        terms_found = [(m.group("term"), p) for p in paragraphs if (m := _TERM.match(p))]
        if len(terms_found) >= MIN_TERMS:
            out += [Entry(article, s, term, p) for term, p in terms_found]
        else:
            out.append(Entry(article, s, s.heading, s.text))
    return out


class HelpIndex:
    COLLECTION = "help"

    def __init__(self, articles: dict[str, Article] | None = None):
        from qdrant_client import QdrantClient, models

        self.articles = articles or load_articles()
        self.embedder = HashEmbedder()
        self.client = QdrantClient(":memory:")
        self.client.create_collection(
            self.COLLECTION, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
        )
        self.entries: list[Entry] = [e for a in self.articles.values() for e in entries_for(a)]
        points = []
        for i, e in enumerate(self.entries):
            text = f"{e.article.title}. {e.heading}. {' '.join(e.article.keywords)}. {e.text}"
            points.append(models.PointStruct(id=i, vector=self.embedder.embed(text)))
        self.client.upsert(self.COLLECTION, points=points, wait=True)
        self._keywords = {a.slug: terms(" ".join(a.keywords)) for a in self.articles.values()}
        # The article's summary is written for search results, so it counts with the heading.
        self._heading = [terms(e.heading) | terms(e.article.title) | terms(e.article.summary) for e in self.entries]
        self._body = [terms(e.text) for e in self.entries]
        # A term's weight: rarer across entries is more telling ("slider" over "engineer").
        # Words outside the corpus weigh as much as the rarest in it, so a question that is
        # mostly about something else scores low everywhere, which is what the refusal
        # threshold relies on.
        df: dict[str, int] = {}
        for i in range(len(self.entries)):
            for t in self._body[i] | self._heading[i] | self._keywords[self.entries[i].article.slug]:
                df[t] = df.get(t, 0) + 1
        n = len(self.entries)
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self._idf_max = max(self._idf.values())

    def _weight(self, t: str) -> float:
        return self._idf.get(t, self._idf_max)

    def _share(self, q: set[str], total: float, have: set[str]) -> float:
        """Weighted share of the question's terms that ``have`` contains."""
        return sum(self._weight(t) for t in q & have) / total

    def search(self, question: str, k: int = 5, slug: str | None = None) -> list[Hit]:
        q = terms(question, expand=True)
        if not q:
            return []
        total = sum(self._weight(t) for t in q)
        points = self.client.query_points(
            self.COLLECTION, query=self.embedder.embed(question), limit=len(self.entries)
        ).points
        hits = []
        for p in points:
            e = self.entries[p.id]
            if slug and e.article.slug != slug:
                continue
            keywords = self._keywords[e.article.slug]
            keyword_share = self._share(q, total, keywords)
            heading_share = self._share(q, total, self._heading[p.id])
            body_share = self._share(q, total, self._body[p.id])  # the entry itself uses these words
            # One shared word is weak evidence, however rare: the lexical boost saturates with
            # the number of distinct words (after stemming) the entry and the question share.
            matched = len({_stem(t) for t in q & (keywords | self._heading[p.id] | self._body[p.id])})
            lexical = (0.5 * keyword_share + 0.5 * heading_share + 0.7 * body_share) * matched / (matched + 0.5)
            score = p.score + lexical
            hits.append(Hit(e.article.slug, e.article.title, e.heading, e.section.anchor, e.text, round(score, 4)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


_index: HelpIndex | None = None
_lock = threading.Lock()


def get_index() -> HelpIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = HelpIndex()
    return _index
