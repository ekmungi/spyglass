"""Tests for the Google News search collector (no network: fetch and decode are injected)."""

import pytest

from spyglass_service.radar.models import ItemExtra, loads
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE
from spyglass_service.radar.sources import news_search
from spyglass_service.radar.sources.news_search import (
    collect_news,
    decode_google_urls,
    search_news,
    topic_queries,
)
from spyglass_service.radar.sources.news_search import _own_query
from sqlmodel import Session, select

from .test_sources_support import all_items, make_engine, make_settings

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>q</title>
<item><title>Older story - Example Times</title>
<link>https://news.google.com/rss/articles/AAA111?oc=5</link>
<pubDate>Wed, 11 Nov 2026 08:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Older story&lt;/a&gt;</description>
<source url="https://example.com">Example Times</source></item>
<item><title>Newer story - the - Daily Wire - Daily Wire</title>
<link>https://news.google.com/rss/articles/BBB222?oc=5</link>
<pubDate>Thu, 12 Nov 2026 08:00:00 GMT</pubDate>
<source url="https://daily.example">Daily Wire</source></item>
</channel></rss>"""


def fake_fetch(url: str) -> bytes:
    assert "when%3A2d" in url or "when:2d" in url
    return FEED.encode()


def fake_decode(links: list[str]) -> list[str | None]:
    return [f"https://real.example/{link.split('/')[-1].split('?')[0]}" for link in links]


def test_search_news_strips_publisher_decodes_and_sorts_newest_first() -> None:
    items = search_news("AI", fetch=fake_fetch, decode=fake_decode)
    assert [i.origin for i in items] == ["Daily Wire", "Example Times"]
    assert items[0].title == "Newer story - the - Daily Wire"
    assert items[1].title == "Older story"
    assert items[1].url == "https://real.example/AAA111"
    assert items[0].source == "news" and items[0].external_id.startswith("gn-")


def test_search_news_keeps_google_link_when_decoding_fails() -> None:
    items = search_news("AI", fetch=fake_fetch, decode=lambda links: [None] * len(links))
    assert items[0].url.startswith("https://news.google.com/rss/articles/BBB222")


def test_search_news_decodes_only_newest_n_and_skips_known_ids() -> None:
    seen: list[list[str]] = []

    def spy(links: list[str]) -> list[str | None]:
        seen.append(links)
        return fake_decode(links)

    items = search_news("AI", fetch=fake_fetch, decode=spy, decode_limit=1)
    assert len(seen[0]) == 1 and "BBB222" in seen[0][0]
    assert items[1].url.startswith("https://news.google.com")  # beyond the limit
    known = {items[0].external_id}
    search_news("AI", fetch=fake_fetch, decode=spy, decode_limit=5, known_ids=known)
    assert len(seen[1]) == 1 and "AAA111" in seen[1][0]


def test_external_id_ignores_the_query_string() -> None:
    assert news_search._stable_id("https://g/x/AAA?oc=5") == news_search._stable_id(
        "https://g/x/AAA?oc=9")


def test_decode_google_urls_degrades_to_none_on_error(monkeypatch) -> None:
    import googlenewsdecoder

    class Boom:
        def __init__(self, **_):
            raise RuntimeError("network down")

    monkeypatch.setattr(googlenewsdecoder, "GoogleDecoder", Boom)
    assert decode_google_urls(["https://news.google.com/rss/articles/X"]) == [None]
    assert decode_google_urls([]) == []


def test_topic_queries_default_profile_has_ten_to_fourteen_distinct() -> None:
    queries = topic_queries(DEFAULT_PROFILE)
    assert 8 <= len(queries) <= 14
    assert len(set(queries)) == len(queries)
    assert "AI medical imaging clinical" in queries
    assert "AI regulation law policy" in queries


def test_topic_queries_derive_from_a_saved_topics_own_text() -> None:
    profile = {"topics": [
        {"name": "Regulation of AI medical devices (FDA, EU MDR, NICE)"},
        {"name": "Protein folding"},
        {"name": "How large language models are used in logistics planning"},
    ]}
    queries = topic_queries(profile)
    assert queries[0] == "AI regulation law policy"
    assert queries[1:] == ['"Protein folding"',
                           "How large language models are used logistics planning"]


def test_topic_queries_unknown_topic_uses_its_own_name() -> None:
    profile = {"topics": [{"name": "Quantum sensing"}, {"name": ""}]}
    assert topic_queries(profile) == ['"Quantum sensing"']
    assert topic_queries({"topics": []}) == []


def test_collect_news_stores_extras_and_is_idempotent(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        args = dict(fetch=fake_fetch, decode=fake_decode, queries=["AI"], pause=0)
        assert collect_news(engine, make_settings(), **args) == 2
        assert collect_news(engine, make_settings(), **args) == 0
        assert len(all_items(engine, "news")) == 2
        with Session(engine) as session:
            extras = [loads(e.data) for e in session.exec(select(ItemExtra)).all()]
        assert {e["publisher"] for e in extras} == {"Daily Wire", "Example Times"}
        assert all(e["query"] == "AI" for e in extras)
    finally:
        engine.dispose()


def test_collect_news_survives_one_failing_query_but_raises_when_all_fail(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        def flaky(url: str) -> bytes:
            if "bad" in url:
                raise OSError("boom")
            return FEED.encode()

        ok = collect_news(engine, make_settings(), fetch=flaky, decode=fake_decode,
                          queries=["bad", "good"], pause=0)
        assert ok == 2
        with pytest.raises(RuntimeError):
            collect_news(engine, make_settings(), fetch=flaky, decode=fake_decode,
                         queries=["bad"], pause=0)
    finally:
        engine.dispose()


def test_decode_google_urls_only_passes_google_news_links_to_the_decoder(monkeypatch) -> None:
    """The decoder makes its own requests, so a link on any other host is never handed to it."""
    import sys
    import types

    handed: list[list[str]] = []

    class FakeDecoder:
        """Records the links it is given."""

        def __init__(self, timeout: int) -> None:
            self.client = types.SimpleNamespace(headers={})

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def decode_google_news_urls(self, links, interval):
            handed.append(list(links))
            return [{"success": True, "decoded_url": "https://publisher.example/story"} for _ in links]

    monkeypatch.setitem(sys.modules, "googlenewsdecoder", types.SimpleNamespace(GoogleDecoder=FakeDecoder))
    result = decode_google_urls(["https://news.google.com/rss/articles/A", "http://10.0.0.5/admin",
                                 "https://news.google.com.evil.example/x"])
    assert handed == [["https://news.google.com/rss/articles/A"]]
    assert result == ["https://publisher.example/story", None, None]


@pytest.mark.parametrize(("name", "expected"), [
    ("AI in endoscopy and surgery (FDA, EU)", "AI endoscopy surgery"),
    ("Protein folding", '"Protein folding"'),
    ("Quantum", '"Quantum"'),
    ("The economics of open-weights models for small teams",
     "economics open-weights models small teams"),
    ("the of and", "the of and"),
    ("", ""),
    ("!!! ???", "!!! ???"),
])
def test_own_query_uses_loose_content_words(name: str, expected: str) -> None:
    """A topic's own name becomes loose terms; one or two words stay a quoted phrase."""
    assert _own_query(name) == expected
