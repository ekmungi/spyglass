"""Tests for feed_discovery.py: discover() function + POST /api/feeds/discover endpoint.

TDD RED phase: all tests written before implementation exists.
Uses httpx.MockTransport + local HTML/XML fixtures; NO real network calls.
Validator monkeypatched so tests never hit the reader DB against live URLs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_WITH_FEEDS = (FIXTURES / "page_with_feeds.html").read_text()
PAGE_NO_FEEDS = (FIXTURES / "page_no_declared_feeds.html").read_text()
SECTION_WITH_FEED = (FIXTURES / "section_with_feed.html").read_text()
DISCOVERY_FEED_PATH = FIXTURES / "discovery_feed.xml"
DISCOVERY_FEED_CONTENT = DISCOVERY_FEED_PATH.read_bytes()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_url(path: Path) -> str:
    """Return a file:// URL for a local path (cross-platform)."""
    return path.as_uri()


def _validator_ok(url: str, _reader_db_path: Path) -> tuple[str, str]:
    """Stub validator: any URL that ends with .xml is a valid feed named 'Stub Feed'."""
    if url.endswith(".xml"):
        return "Stub Feed", "rss"
    raise _not_a_feed(url)


def _not_a_feed(url: str):  # type: ignore[return]
    from spyglass_service.feed_registry import NotAFeedError
    raise NotAFeedError(url)


def _validator_reject(url: str, _reader_db_path: Path) -> tuple[str, str]:
    """Stub validator that rejects every URL."""
    _not_a_feed(url)


# ---------------------------------------------------------------------------
# MockTransport builders
# ---------------------------------------------------------------------------


def _html_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


def _xml_response(body: bytes) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"content-type": "application/rss+xml; charset=utf-8"}
    )


def _404_response() -> httpx.Response:
    return httpx.Response(404, text="Not Found")


class _CallCounter:
    """Wraps a handler and counts how many times it was called."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return self._handler(request)


# ---------------------------------------------------------------------------
# discover() — shallow tier
# ---------------------------------------------------------------------------


def test_shallow_finds_declared_link_rel_alternate_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shallow discovery parses <link rel=alternate rss/atom> and returns validated candidates."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("", "/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)

    assert result.reason is None
    feed_urls = {c.feed_url for c in result.candidates}
    assert "http://example.test/feed.xml" in feed_urls
    assert "http://example.test/atom.xml" in feed_urls


def test_shallow_resolves_relative_hrefs_against_page_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative hrefs like /feed.xml must be resolved to absolute URLs."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)
    for c in result.candidates:
        assert c.feed_url.startswith("http://"), f"Expected absolute URL, got {c.feed_url!r}"


def test_shallow_candidate_already_subscribed_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """already_subscribed=True when the candidate URL is in registry_urls."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover(
        "http://example.test/page",
        depth=0,
        client=client,
        registry_urls={"http://example.test/feed.xml"},
    )
    by_url = {c.feed_url: c for c in result.candidates}
    assert by_url["http://example.test/feed.xml"].already_subscribed is True
    assert by_url["http://example.test/atom.xml"].already_subscribed is False


def test_shallow_non_feed_candidate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidates that fail validation are silently excluded from results."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # Reject everything — no candidates should survive
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_reject)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)
    assert result.candidates == []


def test_shallow_deduplicates_same_resolved_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate candidate URLs collapse to a single Candidate."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    # Page with two <link> tags pointing at the same URL
    html = """<html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
    </head><body></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(html)
        if path == "/feed.xml":
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)
    urls = [c.feed_url for c in result.candidates]
    assert len(urls) == len(set(urls)), "Duplicate candidates not collapsed"


# ---------------------------------------------------------------------------
# discover() — deep tier
# ---------------------------------------------------------------------------


def test_deep_probes_common_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deep discovery probes /feed, /rss, /atom.xml, /feed.xml, /index.xml, /sitemap.xml.

    The probe happens via _validate_feed (reader-based), which is monkeypatched here
    to accept any .xml URL.  We verify the probe occurred by asserting that the known
    common-path feed URL appears in the candidates — it can only appear if the prober
    generated and validated that URL.
    """
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()
    validated: list[str] = []

    def tracking_validator(url: str, db: Any) -> tuple[str, str]:
        validated.append(url)
        return _validator_ok(url, db)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_NO_FEEDS)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", tracking_validator)

    result = feed_discovery.discover("http://example.test/page", depth=1, client=client)

    # The common probe paths must have been submitted to the validator.
    validated_paths = {url.split("example.test", 1)[-1] for url in validated}
    assert any(p in validated_paths for p in ("/feed", "/rss", "/atom.xml", "/feed.xml", "/index.xml"))
    # The /feed.xml probe URL validated successfully (ends with .xml -> accepted by stub).
    found_urls = {c.feed_url for c in result.candidates}
    assert "http://example.test/feed.xml" in found_urls


def test_deep_crawls_section_links_one_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deep discovery crawls in-page links one level to find per-section feeds."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_NO_FEEDS)
        if path == "/section/ai":
            return _html_response(SECTION_WITH_FEED)
        if path == "/section/ai/feed.xml":
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=1, client=client)

    found_urls = {c.feed_url for c in result.candidates}
    assert "http://example.test/section/ai/feed.xml" in found_urls


def test_deep_does_not_recurse_beyond_one_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deep crawl must stop at one level — never follow links found in crawled sections."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()
    fetched_paths: list[str] = []

    # section/ai links to /section/ai/sub — deep should NOT follow that sub-link
    section_html = """<html><head>
      <link rel="alternate" type="application/rss+xml" href="/section/ai/feed.xml">
    </head><body>
      <a href="/section/ai/sub">Sub-section (must not be crawled)</a>
    </body></html>"""

    sub_section_html = """<html><head>
      <link rel="alternate" type="application/rss+xml" href="/section/ai/sub/feed.xml">
    </head><body></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        fetched_paths.append(path)
        if path in ("/", "/page"):
            return _html_response(PAGE_NO_FEEDS)
        if path == "/section/ai":
            return _html_response(section_html)
        if path in ("/section/ai/feed.xml", "/section/ai/sub/feed.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        if path == "/section/ai/sub":
            return _html_response(sub_section_html)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    feed_discovery.discover("http://example.test/page", depth=1, client=client)

    assert "/section/ai/sub" not in fetched_paths, "Recursed beyond one level"


# ---------------------------------------------------------------------------
# Bounds (E.4-E.6) — each must return empty-with-reason, never raise
# ---------------------------------------------------------------------------


def test_dead_site_returns_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 on the root page returns empty candidates + a reason string."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/missing", depth=0, client=client)

    assert result.candidates == []
    assert result.reason is not None
    assert len(result.reason) > 0


def test_non_html_content_type_returns_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page served as image/png (non-HTML) returns empty candidates + reason."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/logo.png", depth=0, client=client)

    assert result.candidates == []
    assert result.reason is not None


def test_oversized_body_returns_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page whose body exceeds the 2MB cap returns empty candidates + reason."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    # 2.1 MB of HTML
    big_body = b"<html><body>" + b"x" * (2 * 1024 * 1024 + 100) + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=big_body, headers={"content-type": "text/html; charset=utf-8"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/huge", depth=0, client=client)

    assert result.candidates == []
    assert result.reason is not None


def test_network_error_returns_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error returns empty candidates + reason, never raises."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://dead.example.test/", depth=0, client=client)

    assert result.candidates == []
    assert result.reason is not None


def test_redirect_to_non_html_returns_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect that ends at a non-HTML resource returns empty + reason."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/doc", depth=0, client=client)

    assert result.candidates == []
    assert result.reason is not None


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


def test_cache_prevents_second_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second discover(url, depth) call with the same args must not re-fetch."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    counter = _CallCounter(
        lambda request: _html_response(PAGE_WITH_FEEDS)
        if request.url.path in ("/", "/page")
        else _xml_response(DISCOVERY_FEED_CONTENT)
        if request.url.path in ("/feed.xml", "/atom.xml")
        else _404_response()
    )

    client = httpx.Client(transport=httpx.MockTransport(counter))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result1 = feed_discovery.discover("http://example.test/page", depth=0, client=client)
    calls_after_first = counter.calls

    result2 = feed_discovery.discover("http://example.test/page", depth=0, client=client)

    assert counter.calls == calls_after_first, "Cache miss: second call re-fetched"
    assert result1.candidates == result2.candidates


def test_cache_different_depths_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """depth=0 and depth=1 are different cache keys — both fetch on first call."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    counter = _CallCounter(
        lambda request: _html_response(PAGE_WITH_FEEDS)
        if request.url.path in ("/", "/page")
        else _xml_response(DISCOVERY_FEED_CONTENT)
        if request.url.path in ("/feed.xml", "/atom.xml")
        else _404_response()
    )

    client = httpx.Client(transport=httpx.MockTransport(counter))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    feed_discovery.discover("http://example.test/page", depth=0, client=client)
    calls_after_shallow = counter.calls

    feed_discovery.discover("http://example.test/page", depth=1, client=client)
    assert counter.calls > calls_after_shallow, "depth=1 should have fetched more"


def test_cache_size_cap_never_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache size must never exceed _CACHE_MAX_ENTRIES even after many distinct inserts."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_reject)

    # Insert more entries than the cap via distinct URLs.
    n = feed_discovery._CACHE_MAX_ENTRIES + 20
    for i in range(n):
        url = f"http://host{i}.test/page"

        def handler(request: httpx.Request, _i: int = i) -> httpx.Response:
            return _html_response(PAGE_NO_FEEDS)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        feed_discovery.discover(url, depth=0, client=client)

    assert len(feed_discovery._CACHE) <= feed_discovery._CACHE_MAX_ENTRIES, (
        f"Cache grew to {len(feed_discovery._CACHE)}, expected <= {feed_discovery._CACHE_MAX_ENTRIES}"
    )


def test_cache_expired_entry_evicted_on_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry past its TTL is purged when a new insert occurs."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_reject)

    stale_key = ("http://stale.test/", 0)
    # Plant a stale entry directly — expiry already in the past.
    feed_discovery._CACHE[stale_key] = (feed_discovery.DiscoverResult(reason="old"), 0.0)

    # Trigger an insert for a different URL — this must sweep the stale entry.
    def handler(request: httpx.Request) -> httpx.Response:
        return _html_response(PAGE_NO_FEEDS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    feed_discovery.discover("http://fresh.test/", depth=0, client=client)

    assert stale_key not in feed_discovery._CACHE, "Stale (expired) entry was not evicted on insert"


def test_cache_fresh_entry_still_a_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A within-TTL entry is NOT evicted and remains a cache hit (existing behavior)."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    counter = _CallCounter(
        lambda request: _html_response(PAGE_WITH_FEEDS)
        if request.url.path in ("/", "/page")
        else _xml_response(DISCOVERY_FEED_CONTENT)
        if request.url.path in ("/feed.xml", "/atom.xml")
        else _404_response()
    )
    client = httpx.Client(transport=httpx.MockTransport(counter))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    # First call — populates cache.
    feed_discovery.discover("http://example.test/page", depth=0, client=client)
    calls_after_first = counter.calls

    # Second call — must hit cache without re-fetching.
    feed_discovery.discover("http://example.test/page", depth=0, client=client)
    assert counter.calls == calls_after_first, (
        "Fresh cache entry was not honoured — second call re-fetched"
    )


# ---------------------------------------------------------------------------
# Candidate shape
# ---------------------------------------------------------------------------


def test_candidate_has_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each Candidate carries feed_url, name, kind, already_subscribed."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)

    assert len(result.candidates) > 0
    for c in result.candidates:
        assert isinstance(c.feed_url, str) and c.feed_url
        assert isinstance(c.name, str) and c.name
        assert isinstance(c.kind, str) and c.kind
        assert isinstance(c.already_subscribed, bool)


# ---------------------------------------------------------------------------
# YouTube channel URL -> feeds/videos.xml via resolve_feed_url
# ---------------------------------------------------------------------------


def test_shallow_youtube_channel_url_resolves_to_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A YouTube /channel/UCxxxx URL is rewritten to feeds/videos.xml without network.

    resolve_feed_url rewrites /channel/UC... purely via regex — no HTTP call needed.
    The test stays fully offline: MockTransport handles only the HTML page fetch and
    _validate_feed is monkeypatched so the reader never hits the network.
    """
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    channel_url = "https://www.youtube.com/channel/UCxxxxSOMEID"
    expected_feed = "https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxSOMEID"

    # The HTML page itself has no declared feeds — YouTube channel pages have none.
    channel_html = "<html><head></head><body><p>Channel page</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        # Serve the channel page as HTML; everything else 404.
        if "youtube.com/channel/" in str(request.url):
            return _html_response(channel_html)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def yt_validator_ok(url: str, _reader_db_path: Path) -> tuple[str, str]:
        """Accept only the expected feed URL so the test is precise."""
        if url == expected_feed:
            return "Test YT Channel", "youtube"
        raise _not_a_feed(url)

    monkeypatch.setattr(feed_discovery, "_validate_feed", yt_validator_ok)

    result = feed_discovery.discover(channel_url, depth=0, client=client)

    feed_urls = {c.feed_url for c in result.candidates}
    assert expected_feed in feed_urls, (
        f"Expected YouTube feed {expected_feed!r} in candidates; got {feed_urls!r}"
    )
    yt_candidate = next(c for c in result.candidates if c.feed_url == expected_feed)
    assert yt_candidate.kind == "youtube"


# ---------------------------------------------------------------------------
# parse_section_links caps at exactly MAX_CRAWL_LINKS (= 25)
# ---------------------------------------------------------------------------


def test_parse_section_links_caps_at_max_crawl_links() -> None:
    """parse_section_links returns at most MAX_CRAWL_LINKS urls even when given 30+ links."""
    from spyglass_service.feed_discovery_html import MAX_CRAWL_LINKS, parse_section_links

    base = "http://example.test/"
    # Build a page with 30 distinct same-origin links — all must be parseable candidates.
    links = "\n".join(
        f'<a href="/section/{i}">Section {i}</a>' for i in range(30)
    )
    html = f"<html><body>{links}</body></html>"

    result = parse_section_links(html, base)

    assert len(result) == MAX_CRAWL_LINKS, (
        f"Expected exactly {MAX_CRAWL_LINKS} links; got {len(result)}"
    )


# ---------------------------------------------------------------------------
# POST /api/feeds/discover endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_client(tmp_path: Path) -> TestClient:
    """Minimal FastAPI test client with the feeds router mounted."""
    from fastapi import FastAPI
    from sqlmodel import SQLModel

    from spyglass_service.api_feeds import router
    from spyglass_service.db import create_db_engine

    engine = create_db_engine(tmp_path / "test.db")
    SQLModel.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine

    # Provide a minimal service_state stub for endpoints that need it
    class _ServiceState:
        def ensure_index(self) -> Any:
            raise RuntimeError("ensure_index not expected in this test")

    app.state.service_state = _ServiceState()
    app.state.settings = None

    return TestClient(app)


def test_discover_endpoint_returns_candidates(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/feeds/discover returns a list of candidate dicts."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    def fake_discover(url: str, depth: int, *, registry_urls=None, client=None):
        return feed_discovery.discover(
            url, depth, registry_urls=registry_urls or set(), client=mock_client
        )

    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)
    monkeypatch.setattr("spyglass_service.api_feeds.discover", fake_discover)

    resp = app_client.post("/api/feeds/discover", json={"url": "http://example.test/page", "depth": 0})

    assert resp.status_code == 200
    body = resp.json()
    assert "candidates" in body
    assert isinstance(body["candidates"], list)


def test_discover_endpoint_422_on_missing_url(app_client: TestClient) -> None:
    """POST /api/feeds/discover with no url field returns 422."""
    resp = app_client.post("/api/feeds/discover", json={"depth": 0})
    assert resp.status_code == 422


def test_discover_endpoint_reason_on_dead_site(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/feeds/discover on a dead site returns empty candidates + reason."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def fake_discover(url: str, depth: int, *, registry_urls=None, client=None):
        return feed_discovery.DiscoverResult(candidates=[], reason="HTTP 404")

    monkeypatch.setattr("spyglass_service.api_feeds.discover", fake_discover)

    resp = app_client.post("/api/feeds/discover", json={"url": "http://dead.example.test/", "depth": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"] == []
    assert body["reason"] == "HTTP 404"


# ---------------------------------------------------------------------------
# reason_code — typed fetch failure codes
# ---------------------------------------------------------------------------


def test_reason_code_blocked_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 403 on the initial fetch sets reason_code='blocked'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/blocked", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "blocked"
    assert result.reason is not None


def test_reason_code_blocked_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 (rate limited) on the initial fetch sets reason_code='blocked'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/ratelimited", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "blocked"


def test_reason_code_blocked_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 503 (service unavailable / WAF block) on the initial fetch sets reason_code='blocked'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/blocked503", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "blocked"


def test_reason_code_blocked_on_cloudflare_challenge_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response whose body starts with a Cloudflare challenge sets reason_code='blocked'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    # Cloudflare serves a 200 with text/html containing "Just a moment"
    cf_body = (
        "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        "<body><p>Checking your browser before accessing the site.</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=cf_body, headers={"content-type": "text/html; charset=utf-8"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://cf-gated.example.test/", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "blocked"


def test_reason_code_blocked_on_cf_mitigated_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response containing 'cf-mitigated' in the first 1KB sets reason_code='blocked'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    cf_body = "<!DOCTYPE html><html><head><meta name='cf-mitigated' content='challenge'/></head></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=cf_body, headers={"content-type": "text/html; charset=utf-8"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://cf-gated2.example.test/", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "blocked"


def test_reason_code_not_html_on_json_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response with content-type application/json sets reason_code='not_html'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"key": "value"}',
            headers={"content-type": "application/json"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/api/data", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "not_html"


def test_reason_code_too_large_on_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body exceeding _MAX_BODY_BYTES sets reason_code='too_large'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    big_body = b"<html><body>" + b"x" * (2 * 1024 * 1024 + 100) + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=big_body, headers={"content-type": "text/html; charset=utf-8"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/huge2", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "too_large"


def test_reason_code_network_error_on_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network-level connection error sets reason_code='network_error'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://dead2.example.test/", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "network_error"


def test_reason_code_none_when_candidates_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """When feeds are discovered successfully, reason_code is None (regression guard)."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("", "/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)

    assert len(result.candidates) > 0
    assert result.reason_code is None


def test_reason_code_no_feeds_when_page_ok_but_no_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successfully fetched page with no feeds sets reason_code='no_feeds'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("", "/", "/page"):
            return _html_response(PAGE_NO_FEEDS)
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # Reject every URL as a feed so the common-path probes don't accidentally succeed
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_reject)

    result = feed_discovery.discover("http://example.test/page", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "no_feeds"


def test_reason_code_http_error_on_non_blocked_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-200 response that is not 403/429/503 sets reason_code='http_error'."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/server-error", depth=0, client=client)

    assert result.candidates == []
    assert result.reason_code == "http_error"


def test_section_crawl_failure_does_not_set_top_level_reason_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed section-link fetch (deep tier) must not override the top-level reason_code.

    The initial page loads successfully, so reason_code should be None when candidates
    are found, even if section-link fetches fail.
    """
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("", "/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        # Section links return 403 — must not propagate to top-level reason_code
        if path.startswith("/section/"):
            return httpx.Response(403, text="Forbidden")
        return _404_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)

    result = feed_discovery.discover("http://example.test/page", depth=1, client=client)

    # Candidates found from the initial page (declared feeds) — reason_code must be None
    assert result.reason_code is None


def test_discover_endpoint_returns_reason_code(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/feeds/discover returns reason_code in the JSON response."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def fake_discover(url: str, depth: int, *, registry_urls=None, client=None):
        return feed_discovery.DiscoverResult(
            candidates=[],
            reason="This site blocked automated access (it needs a real browser, e.g. a Cloudflare challenge).",
            reason_code="blocked",
        )

    monkeypatch.setattr("spyglass_service.api_feeds.discover", fake_discover)

    resp = app_client.post(
        "/api/feeds/discover", json={"url": "http://cf-gated.example.test/", "depth": 0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"] == []
    assert body["reason_code"] == "blocked"


def test_discover_endpoint_reason_code_none_on_success(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/feeds/discover returns reason_code=null when candidates are found."""
    from spyglass_service import feed_discovery

    feed_discovery._CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/", "/page"):
            return _html_response(PAGE_WITH_FEEDS)
        if path in ("/feed.xml", "/atom.xml"):
            return _xml_response(DISCOVERY_FEED_CONTENT)
        return _404_response()

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    def fake_discover(url: str, depth: int, *, registry_urls=None, client=None):
        return feed_discovery.discover(
            url, depth, registry_urls=registry_urls or set(), client=mock_client
        )

    monkeypatch.setattr(feed_discovery, "_validate_feed", _validator_ok)
    monkeypatch.setattr("spyglass_service.api_feeds.discover", fake_discover)

    resp = app_client.post(
        "/api/feeds/discover", json={"url": "http://example.test/page", "depth": 0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) > 0
    assert body["reason_code"] is None
