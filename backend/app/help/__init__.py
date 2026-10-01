"""Help center content: Markdown articles with a small front-matter header.

The articles in ``articles/`` are the single source for the in-app help center and the
assistant's knowledge. They're validated at startup (like fab profiles), so a broken link
or missing title fails CI rather than showing up in production.

Front matter (between ``---`` lines)::

    title: Live dispatch
    summary: One sentence for lists and search results.
    section: Get started | Planning | Live dispatch | Reference
    order: 1
    keywords: [comma, separated, terms people search for]

Links to other articles use ``help:slug`` or ``help:slug#anchor``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

ARTICLES_DIR = Path(__file__).parent / "articles"
SECTIONS = ["Get started", "Planning", "Live dispatch", "Reference"]
_LINK = re.compile(r"\(help:([a-z0-9-]+)(?:#([a-z0-9-]+))?\)")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class Section(BaseModel):
    heading: str
    anchor: str
    text: str


class Article(BaseModel):
    slug: str
    title: str
    summary: str
    section: str
    order: int
    keywords: list[str] = Field(default_factory=list)
    body: str
    sections: list[Section]

    def summary_view(self) -> dict:
        return {"slug": self.slug, "title": self.title, "summary": self.summary}


class HelpError(ValueError):
    pass


def _front_matter(raw: str, name: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise HelpError(f"{name}: missing front matter")
    meta: dict = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, m.group(2).strip() + "\n"


def _split(body: str, title: str) -> list[Section]:
    """Sections by ``## `` heading; text before the first one belongs to the title."""
    parts = re.split(r"^## (.+)$", body, flags=re.M)
    intro = re.sub(r"^# .+\n", "", parts[0]).strip()
    sections = [Section(heading=title, anchor="", text=intro)] if intro else []
    for heading, text in zip(parts[1::2], parts[2::2], strict=True):
        sections.append(Section(heading=heading.strip(), anchor=slugify(heading), text=text.strip()))
    return sections


def parse(slug: str, raw: str) -> Article:
    meta, body = _front_matter(raw, slug)
    missing = {"title", "summary", "section", "order"} - meta.keys()
    if missing:
        raise HelpError(f"{slug}: missing {sorted(missing)}")
    if meta["section"] not in SECTIONS:
        raise HelpError(f"{slug}: unknown section {meta['section']!r}")
    return Article(
        slug=slug,
        title=meta["title"],
        summary=meta["summary"],
        section=meta["section"],
        order=int(meta["order"]),
        keywords=meta.get("keywords", []),
        body=body,
        sections=_split(body, meta["title"]),
    )


@lru_cache
def load_articles(directory: Path = ARTICLES_DIR) -> dict[str, Article]:
    articles = {p.stem: parse(p.stem, p.read_text()) for p in sorted(directory.glob("*.md"))}
    for a in articles.values():
        for slug, anchor in _LINK.findall(a.body):
            if slug not in articles:
                raise HelpError(f"{a.slug}: link to unknown article {slug!r}")
            if anchor and anchor not in {s.anchor for s in articles[slug].sections}:
                raise HelpError(f"{a.slug}: link to unknown section {slug}#{anchor}")
    return articles


def get_article(slug: str) -> Article | None:
    return load_articles().get(slug)


def table_of_contents() -> list[dict]:
    articles = load_articles().values()
    return [
        {
            "name": name,
            "articles": [a.summary_view() for a in sorted(articles, key=lambda a: a.order) if a.section == name],
        }
        for name in SECTIONS
    ]
