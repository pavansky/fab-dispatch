"""Prepare the documentation site: generate the pages that have another single source.

    python docs/build.py && mkdocs build --strict      (or: make docs)

* ``docs/guide/``  the in-app help articles (backend/app/help/articles), so the help center, the
  assistant and the public docs never disagree. ``help:slug#anchor`` links become site links.
* ``docs/project/`` CHANGELOG, SECURITY, CONTRIBUTING and the Supabase guide, with their relative
  links rewritten: to the site when the target is a docs page, to GitHub otherwise.
* ``docs/api/openapi.json``  the live API's OpenAPI schema, rendered by the API reference page.
* ``docs/assets/``  the favicon and link-preview card from the web app.

Everything generated is git-ignored; CI rebuilds it on every deploy.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REPO = "https://github.com/pavansky/fab-dispatch"
LINK = re.compile(r"(\]\()([^)\s]+)(\))")
# Files outside docs/ that the site publishes as pages: link to the page, not to GitHub.
COPIES = {
    ROOT / "CHANGELOG.md": DOCS / "project" / "changelog.md",
    ROOT / "SECURITY.md": DOCS / "project" / "security.md",
    ROOT / "CONTRIBUTING.md": DOCS / "project" / "contributing.md",
    ROOT / "supabase" / "README.md": DOCS / "project" / "supabase.md",
}

sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("FAB_AUTH_MODE", "demo")
os.environ.setdefault("FAB_DATABASE_URL", "sqlite:///:memory:")


def rewrite_links(text: str, source: Path, page: Path) -> str:
    """Make a file's relative links work from ``page``: site-relative if the target is in docs/,
    a GitHub URL otherwise. Absolute URLs and in-page anchors are left alone."""

    def fix(m: re.Match) -> str:
        target = m.group(2)
        if re.match(r"^(https?:|mailto:|#)", target):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = COPIES.get(
            (source.parent / path).resolve(), (source.parent / path).resolve()
        )
        if resolved.is_relative_to(DOCS):  # a page or asset the site publishes
            new = os.path.relpath(resolved, page.parent)
        else:
            kind = "tree" if resolved.is_dir() else "blob"
            new = f"{REPO}/{kind}/main/{resolved.relative_to(ROOT).as_posix()}"
        return f"{m.group(1)}{new}{'#' + anchor if anchor else ''}{m.group(3)}"

    return LINK.sub(fix, text)


def guide() -> None:
    from app.help import SECTIONS, load_articles

    out = DOCS / "guide"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    articles = load_articles()
    for a in articles.values():
        body = re.sub(
            r"\]\(help:([a-z0-9-]+)(#[a-z0-9-]+)?\)",
            lambda m: f"]({m.group(1)}.md{m.group(2) or ''})",
            a.body,
        )
        note = '!!! tip "Also in the app"\n    Press **?** in Fab Dispatch to read this in the help center, or **/** to ask the assistant.\n\n'
        title, rest = body.split("\n", 1)
        edit = f"edit_url: {REPO}/edit/main/backend/app/help/articles/{a.slug}.md"
        (out / f"{a.slug}.md").write_text(
            f"---\n{edit}\n---\n\n{title}\n\n{note}{rest.lstrip()}"
        )
    index = ["# User guide\n", "Everything in the in-app help center, by topic.\n"]
    for name in SECTIONS:
        index.append(f"\n## {name}\n")
        for a in sorted(
            (a for a in articles.values() if a.section == name), key=lambda a: a.order
        ):
            index.append(f"- [{a.title}]({a.slug}.md): {a.summary}")
    (out / "index.md").write_text("\n".join(index) + "\n")


def project_pages() -> None:
    out = DOCS / "project"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for src, page in COPIES.items():
        edit = f"---\nedit_url: {REPO}/edit/main/{src.relative_to(ROOT).as_posix()}\n---\n\n"
        page.write_text(edit + rewrite_links(src.read_text(), src, page))


def api_schema() -> None:
    from app.main import app

    (DOCS / "api").mkdir(exist_ok=True)
    (DOCS / "api" / "openapi.json").write_text(json.dumps(app.openapi(), indent=1))


def assets() -> None:
    for name in ("favicon.svg", "og.png"):
        shutil.copy(ROOT / "frontend" / "public" / name, DOCS / "assets" / name)


def main() -> None:
    guide()
    project_pages()
    api_schema()
    assets()
    print("docs: generated guide/, project/, api/openapi.json and brand assets")


if __name__ == "__main__":
    main()
