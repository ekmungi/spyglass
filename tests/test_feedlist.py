"""Tests for parsing the vault feed-list note into subscription URLs."""

from spyglass_service.collectors.feedlist import parse_feed_list

SAMPLE_NOTE = """---
tags: [spyglass]
---

# My feeds

Machine learning:
- https://example.test/ml.xml
- [arXiv cs.AI](https://example.test/arxiv-ai.xml) daily papers

Ignore this paragraph, it has no links.

https://example.test/plain.xml
"""


def test_extracts_all_urls_from_bullets_links_and_bare_lines() -> None:
    """URLs are found in bullets, markdown links, and bare lines alike."""
    urls = parse_feed_list(SAMPLE_NOTE)
    assert urls == [
        "https://example.test/ml.xml",
        "https://example.test/arxiv-ai.xml",
        "https://example.test/plain.xml",
    ]


def test_markdown_link_punctuation_is_not_included() -> None:
    """The closing parenthesis of [text](url) never leaks into the URL."""
    urls = parse_feed_list("see [x](https://example.test/a.xml).")
    assert urls == ["https://example.test/a.xml"]


def test_duplicate_urls_are_returned_once() -> None:
    """A URL listed twice in the note subscribes once."""
    urls = parse_feed_list("https://example.test/a.xml\nhttps://example.test/a.xml")
    assert urls == ["https://example.test/a.xml"]


def test_empty_or_linkless_note_yields_no_urls() -> None:
    """A new, empty feed note is valid and simply yields nothing."""
    assert parse_feed_list("") == []
    assert parse_feed_list("# heading only\nplain text") == []
