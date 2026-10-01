"""Retrieval over the help center: which section answers this question?

Each article section is one point in an in-memory Qdrant collection, embedded with the
same dependency-free ``HashEmbedder`` as repair history. The corpus ships with the code
(a few dozen sections), so it's rebuilt per process in milliseconds and never goes stale;
it doesn't need the Qdrant server even when repair history uses one.

Ranking is hybrid: vector similarity, plus boosts when the question's terms are the
article's declared keywords, appear in the section heading, or appear in the section text. Short questions ("idle
wait?") carry little vector signal, and keywords are written by people who know the app.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from ..help import Article, load_articles
from ..knowledge import DIM, HashEmbedder

STOPWORDS = set(
    [
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
    ]
)


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
}


def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w  # measure / measured -> measur


def terms(text: str, expand: bool = False) -> set[str]:
    words = [w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower()) if w not in STOPWORDS and len(w) > 1]
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
        self.sections: list[tuple[Article, int]] = []
        points = []
        for a in self.articles.values():
            for i, s in enumerate(a.sections):
                text = f"{a.title}. {s.heading}. {' '.join(a.keywords)}. {s.text}"
                points.append(models.PointStruct(id=len(self.sections), vector=self.embedder.embed(text)))
                self.sections.append((a, i))
        self.client.upsert(self.COLLECTION, points=points, wait=True)
        self._keywords = {a.slug: terms(" ".join(a.keywords)) for a in self.articles.values()}
        self._body = [terms(a.sections[i].text) for a, i in self.sections]

    def search(self, question: str, k: int = 5, slug: str | None = None) -> list[Hit]:
        q = terms(question, expand=True)
        if not q:
            return []
        points = self.client.query_points(
            self.COLLECTION, query=self.embedder.embed(question), limit=len(self.sections)
        ).points
        hits = []
        for p in points:
            article, i = self.sections[p.id]
            if slug and article.slug != slug:
                continue
            section = article.sections[i]
            heading = terms(section.heading) | terms(article.title)
            keyword_share = len(q & self._keywords[article.slug]) / len(q)
            heading_share = len(q & heading) / len(q)
            body_share = len(q & self._body[p.id]) / len(q)  # the section itself uses these words
            score = p.score + 0.45 * keyword_share + 0.35 * heading_share + 0.3 * body_share
            hits.append(
                Hit(article.slug, article.title, section.heading, section.anchor, section.text, round(score, 4))
            )
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
