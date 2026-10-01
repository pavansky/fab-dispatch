"""Help center: content validation and the public help API."""

import pytest
from fastapi.testclient import TestClient

from app.help import SECTIONS, HelpError, load_articles, parse, table_of_contents
from app.main import app

anon = TestClient(app)

GOOD = "---\ntitle: T\nsummary: S\nsection: Reference\norder: 1\nkeywords: [a, b]\n---\n# T\n\nIntro.\n\n## Part one\n\nText.\n"


def test_every_article_loads_with_sections_and_keywords():
    articles = load_articles()
    assert len(articles) >= 15
    for a in articles.values():
        assert a.title and a.summary and a.section in SECTIONS
        assert a.keywords, f"{a.slug} has no keywords for search"
        assert a.sections, f"{a.slug} has no content"


def test_table_of_contents_follows_section_and_article_order():
    toc = table_of_contents()
    assert [s["name"] for s in toc] == SECTIONS
    assert toc[0]["articles"][0]["slug"] == "getting-started"
    assert sum(len(s["articles"]) for s in toc) == len(load_articles())


def test_parse_splits_sections_with_anchors():
    a = parse("t", GOOD)
    assert [s.anchor for s in a.sections] == ["", "part-one"]
    assert a.keywords == ["a", "b"]


@pytest.mark.parametrize(
    "raw, error",
    [
        ("# no front matter\n", "missing front matter"),
        ("---\ntitle: T\n---\nbody\n", "missing"),
        (GOOD.replace("Reference", "Elsewhere"), "unknown section"),
    ],
)
def test_bad_articles_are_rejected(raw, error):
    with pytest.raises(HelpError, match=error):
        parse("bad", raw)


def test_broken_links_fail_at_load(tmp_path):
    (tmp_path / "a.md").write_text(GOOD + "\nSee [b](help:missing).\n")
    load_articles.cache_clear()
    try:
        with pytest.raises(HelpError, match="unknown article"):
            load_articles(tmp_path)
        (tmp_path / "a.md").write_text(GOOD + "\nSee [b](help:a#nowhere).\n")
        with pytest.raises(HelpError, match="unknown section"):
            load_articles(tmp_path)
    finally:
        load_articles.cache_clear()


def test_help_is_public_and_cacheable():
    r = anon.get("/api/help")
    assert r.status_code == 200
    assert [s["name"] for s in r.json()["sections"]] == SECTIONS
    again = anon.get("/api/help", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_help_article_and_404():
    r = anon.get("/api/help/live-dispatch")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Live dispatch"
    assert "## Drive the clock" in body["body"]
    assert {"heading": "Drive the clock", "anchor": "drive-the-clock"} in body["sections"]
    assert anon.get("/api/help/nope").status_code == 404


def test_help_search_finds_the_right_article_and_nothing_for_nonsense():
    hits = anon.get("/api/help/search", params={"q": "idle wait"}).json()["results"]
    assert hits[0]["slug"] == "metrics"
    assert len({h["slug"] for h in hits}) == len(hits)  # one result per article
    assert anon.get("/api/help/search", params={"q": "zzzz qqqq"}).json()["results"] == []
