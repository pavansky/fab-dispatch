"""MkDocs hook: links in docs/*.md that point outside docs/ (e.g. ../.env.example) become GitHub
links, or site links for files the site publishes (see build.py COPIES)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "docs_build", Path(__file__).with_name("build.py")
)
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)


def on_page_markdown(markdown, page, config, files):
    src = Path(page.file.abs_src_path)
    if src.parent.name in {
        "guide",
        "project",
    }:  # generated pages: links already resolved
        return markdown
    return _build.rewrite_links(markdown, src, src)


def on_page_context(context, page, config, nav):
    # Generated pages edit their source (a help article, CHANGELOG.md, …), not the generated copy.
    if page.meta.get("edit_url"):
        page.edit_url = page.meta["edit_url"]
    return context
