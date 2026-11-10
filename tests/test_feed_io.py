"""Tests for feed_io: OPML parse/build and markdown build helpers.

All tests are pure-function; no network, no DB, no filesystem side-effects.
"""

import textwrap

import pytest

from spyglass_service.feed_io import OPMLParseError, build_markdown, build_opml, parse_opml
from spyglass_service.models import Feed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed(url: str, name: str = "Test Feed") -> Feed:
    """Construct an unsaved Feed stub sufficient for build_opml / build_markdown.

    Args:
        url: The feed_url to use.
        name: Display name for the feed.

    Returns:
        Feed instance (no id; not persisted to DB).
    """
    return Feed(
        feed_url=url,
        name=name,
        kind="rss",
        added_via="manual",
        enabled=True,
    )


# ---------------------------------------------------------------------------
# parse_opml
# ---------------------------------------------------------------------------

FLAT_OPML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <opml version="2.0">
      <head><title>My Feeds</title></head>
      <body>
        <outline type="rss" text="Feed A" xmlUrl="https://a.example.com/feed"/>
        <outline type="rss" text="Feed B" xmlUrl="https://b.example.com/rss"/>
      </body>
    </opml>
    """
)

NESTED_OPML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <opml version="2.0">
      <head><title>Nested</title></head>
      <body>
        <outline text="Tech" title="Tech">
          <outline type="rss" text="TechCrunch" xmlUrl="https://tc.example.com/feed"/>
          <outline text="AI" title="AI">
            <outline type="rss" text="OpenAI" xmlUrl="https://openai.example.com/rss"/>
          </outline>
        </outline>
        <outline type="rss" text="Science" xmlUrl="https://sci.example.com/feed"/>
      </body>
    </opml>
    """
)

FOLDER_ONLY_OPML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <opml version="2.0">
      <head><title>Folders Only</title></head>
      <body>
        <outline text="Folder A" title="Folder A">
          <outline text="Sub Folder" title="Sub Folder"/>
        </outline>
      </body>
    </opml>
    """
)

MALFORMED_OPML = "<opml><body><outline xmlUrl='https://x.com/feed'</body></opml>"


def test_parse_opml_flat_extracts_all_xml_urls() -> None:
    """parse_opml returns all xmlUrl values from a flat OPML body."""
    urls = parse_opml(FLAT_OPML)
    assert urls == ["https://a.example.com/feed", "https://b.example.com/rss"]


def test_parse_opml_nested_recurses_into_folders() -> None:
    """parse_opml recurses through folder outlines and still finds xmlUrls."""
    urls = parse_opml(NESTED_OPML)
    assert set(urls) == {
        "https://tc.example.com/feed",
        "https://openai.example.com/rss",
        "https://sci.example.com/feed",
    }
    assert len(urls) == 3


def test_parse_opml_folder_outlines_without_xml_url_are_ignored() -> None:
    """Folder outlines (no xmlUrl attribute) are not included in results."""
    urls = parse_opml(FOLDER_ONLY_OPML)
    assert urls == []


def test_parse_opml_malformed_xml_raises_opml_parse_error() -> None:
    """parse_opml raises OPMLParseError (not a raw ParseError) on malformed XML."""
    with pytest.raises(OPMLParseError):
        parse_opml(MALFORMED_OPML)


def test_parse_opml_empty_body_returns_empty_list() -> None:
    """An OPML with an empty body returns an empty list without error."""
    opml = (
        '<?xml version="1.0"?>'
        '<opml version="2.0"><head><title>Empty</title></head><body></body></opml>'
    )
    assert parse_opml(opml) == []


def test_parse_opml_single_feed() -> None:
    """A single-feed OPML returns a one-element list."""
    opml = (
        '<?xml version="1.0"?>'
        '<opml version="2.0"><head/><body>'
        '<outline xmlUrl="https://solo.example.com/feed"/>'
        "</body></opml>"
    )
    assert parse_opml(opml) == ["https://solo.example.com/feed"]


# ---------------------------------------------------------------------------
# build_opml
# ---------------------------------------------------------------------------


def test_build_opml_produces_valid_xml_with_one_outline_per_feed() -> None:
    """build_opml emits one <outline> per feed with correct attributes."""
    feeds = [
        _feed("https://a.example.com/feed", "Feed A"),
        _feed("https://b.example.com/rss", "Feed B"),
    ]
    result = build_opml(feeds)
    assert "https://a.example.com/feed" in result
    assert "https://b.example.com/rss" in result
    assert 'xmlUrl="https://a.example.com/feed"' in result
    assert 'xmlUrl="https://b.example.com/rss"' in result
    # Name attribute present
    assert 'text="Feed A"' in result
    assert 'text="Feed B"' in result


def test_build_opml_round_trips_through_parse_opml() -> None:
    """build_opml output is parseable by parse_opml and yields the same URL set."""
    urls_in = [
        "https://alpha.example.com/feed",
        "https://beta.example.com/rss",
        "https://gamma.example.com/atom",
    ]
    feeds = [_feed(u, f"Feed {i}") for i, u in enumerate(urls_in)]
    opml_text = build_opml(feeds)
    urls_out = parse_opml(opml_text)
    assert set(urls_out) == set(urls_in)
    assert len(urls_out) == len(urls_in)


def test_build_opml_empty_feed_list_produces_valid_xml() -> None:
    """build_opml with no feeds still emits valid parseable OPML."""
    result = build_opml([])
    assert "<opml" in result
    # ET.indent renders empty elements as "<body />" (space before slash)
    assert "<body>" in result or "<body/>" in result or "<body />" in result
    assert parse_opml(result) == []


def test_build_opml_includes_opml_header() -> None:
    """build_opml output includes the expected version attribute and title."""
    result = build_opml([_feed("https://example.com/f")])
    assert 'version="2.0"' in result
    assert "Spyglass" in result


# ---------------------------------------------------------------------------
# build_markdown
# ---------------------------------------------------------------------------


def test_build_markdown_produces_one_line_per_feed() -> None:
    """build_markdown emits one line per feed."""
    feeds = [
        _feed("https://a.example.com/feed", "Alpha"),
        _feed("https://b.example.com/rss", "Beta"),
    ]
    result = build_markdown(feeds)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) == 2


def test_build_markdown_contains_all_urls() -> None:
    """build_markdown output contains every feed URL."""
    urls = ["https://one.example.com/f", "https://two.example.com/f"]
    feeds = [_feed(u) for u in urls]
    result = build_markdown(feeds)
    for url in urls:
        assert url in result


def test_build_markdown_round_trips_through_parse_feed_list() -> None:
    """build_markdown output is parseable by parse_feed_list with the same URL set."""
    from spyglass_service.collectors.feedlist import parse_feed_list  # noqa: PLC0415

    urls_in = ["https://x.example.com/feed", "https://y.example.com/rss"]
    feeds = [_feed(u, f"Feed {i}") for i, u in enumerate(urls_in)]
    markdown_text = build_markdown(feeds)
    urls_out = parse_feed_list(markdown_text)
    assert set(urls_out) == set(urls_in)
    assert len(urls_out) == len(urls_in)


def test_build_markdown_empty_feed_list_returns_empty_or_header() -> None:
    """build_markdown with no feeds returns an empty or header-only string (not a crash)."""
    result = build_markdown([])
    # Must not raise; may be empty or have a header line
    assert isinstance(result, str)
    from spyglass_service.collectors.feedlist import parse_feed_list  # noqa: PLC0415

    assert parse_feed_list(result) == []
