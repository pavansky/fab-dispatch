"""The documentation site stays in step with the app: every help article is in the site's
navigation, and every docs link inside the app points at a page that exists."""

import re
from pathlib import Path

import yaml

from app.help import load_articles

ROOT = Path(__file__).resolve().parents[2]


class _Loader(yaml.SafeLoader):
    pass


# mkdocs.yml uses !!python/name tags for Material's emoji helpers; they don't matter here.
_Loader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None)


def _nav_files(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [f for item in node for f in _nav_files(item)]
    if isinstance(node, dict):
        return [f for v in node.values() for f in _nav_files(v)]
    return []


def test_every_help_article_is_in_the_docs_site_navigation():
    nav = set(_nav_files(yaml.load((ROOT / "mkdocs.yml").read_text(), Loader=_Loader)["nav"]))
    missing = sorted(f"guide/{slug}.md" for slug in load_articles() if f"guide/{slug}.md" not in nav)
    assert not missing, f"add to mkdocs.yml nav: {missing}"


def test_docs_links_in_the_app_point_at_real_pages():
    links = (ROOT / "frontend/src/lib/links.js").read_text()
    pages = re.findall(r"\$\{DOCS\}([a-z0-9-]+)/", links)
    assert pages, "expected docs links in links.js"
    for page in pages:
        assert (ROOT / "docs" / f"{page}.md").exists(), f"links.js points at missing docs page {page}/"
