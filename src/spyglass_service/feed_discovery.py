"""Feed discovery: on-demand, user-initiated, bounded URL-to-feed resolution.

Discovery is USER-INITIATED, BOUNDED, ON-DEMAND — never background scraping.
Exposes discover(url, depth) -> DiscoverResult; all bounds enforced here; callers receive
an empty-with-reason result on any failure, never an exception.

HTML is parsed with BeautifulSoup + stdlib html.parser (no lxml; no XXE surface).
Validation reuses feed_registry._validate_feed so acceptance criteria match add_feed.

_fetch_html returns a typed FetchOutcome distinguishing blocked /
not_html / too_large / http_error / network_error.  DiscoverResult carries reason_code.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from spyglass_service.collectors.rss import resolve_feed_url
from spyglass_service.feed_discovery_html import parse_declared_feeds, parse_section_links
from spyglass_service.feed_registry import NotAFeedError, _validate_feed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bounds and module constants
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES: int = 2 * 1024 * 1024  # 2 MB body cap
_CONNECT_TIMEOUT: float = 5.0
_READ_TIMEOUT: float = 10.0
_COMMON_FEED_PATHS: tuple[str, ...] = (
    "/feed", "/rss", "/atom.xml", "/feed.xml", "/index.xml", "/sitemap.xml",
)
_USER_AGENT: str = "Spyglass/1.0 feed-discovery (+https://github.com/spyglass)"

# In-process result cache keyed by (url, depth); 60s TTL, max 128 entries.
_CACHE_TTL: float = 60.0
_CACHE_MAX_ENTRIES: int = 128
_CACHE: dict[tuple[str, int], tuple["DiscoverResult", float]] = {}

# ---------------------------------------------------------------------------
# Public data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A single discovered feed candidate validated as parseable.

    Attributes:
        feed_url: Resolved, absolute feed URL.
        name: Feed title (from the feed itself, not the page).
        kind: 'youtube' or 'rss'.
        already_subscribed: True when feed_url is already in the registry.
    """

    feed_url: str
    name: str
    kind: str
    already_subscribed: bool


@dataclass(frozen=True)
class FetchOutcome:
    """Typed result of _fetch_html.

    reason_code is None on success (html + final_url are set).
    Failure codes: 'blocked', 'not_html', 'too_large', 'http_error', 'network_error'.
    """

    html: str | None
    final_url: str | None
    reason_code: str | None


# Bot-challenge interstitial markers (Cloudflare et al.), checked case-insensitively on the first ~1KB.
_CHALLENGE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "attention required",
    "checking your browser",
    "cf-browser-verification",
    "cf-mitigated",
)

# HTTP status codes treated as "the site blocked us" rather than a generic error.
_BLOCKED_STATUS_CODES: frozenset[int] = frozenset({403, 429, 503})

# Human-readable messages keyed by reason_code.
_FETCH_REASON_MESSAGES: dict[str, str] = {
    "blocked": "This site blocked automated access (it needs a real browser, e.g. a Cloudflare challenge).",
    "not_html": "That link did not return a web page.",
    "too_large": "That page was too large to scan.",
    "http_error": "The site returned an error while loading that page.",
    "network_error": "Could not reach that site.",
}


@dataclass
class DiscoverResult:
    """Result of a discover() call.

    Attributes:
        candidates: Validated, deduplicated feed candidates (may be empty).
        reason: Human-readable explanation when candidates is empty.  None when non-empty.
        reason_code: Machine-readable code when empty: 'blocked', 'not_html', 'too_large',
            'http_error', 'network_error', 'no_feeds'.  None when candidates is non-empty.
    """

    candidates: list[Candidate] = field(default_factory=list)
    reason: str | None = None
    reason_code: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover(
    url: str,
    depth: int,
    *,
    registry_urls: set[str] | None = None,
    client: httpx.Client | None = None,
) -> DiscoverResult:
    """Discover feed candidates for a given URL, bounded and on-demand.

    Shallow (depth=0): parse <link rel=alternate rss/atom> from the page.
    Deep (depth=1): also probe common paths + crawl in-page links one level.

    Results are cached in-process keyed by (url, depth) for _CACHE_TTL seconds
    so repeated identical calls do not re-fetch (cache does NOT persist across
    process restarts).

    Args:
        url: User-supplied page URL to discover feeds for.
        depth: 0 = shallow only; 1 = deep (probes + one-level crawl).
        registry_urls: Set of already-subscribed feed URLs for already_subscribed
            flag computation. Defaults to empty set.
        client: Optional httpx.Client (inject in tests via MockTransport).
            If omitted a short-lived client is created with bounded timeouts.

    Returns:
        DiscoverResult with validated candidates and optional reason string.
    """
    registry_urls = registry_urls or set()
    cache_key = (url, depth)

    # Check cache first.
    cached = _CACHE.get(cache_key)
    if cached is not None:
        result, expiry = cached
        if time.monotonic() < expiry:
            return result

    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )

    try:
        result = _run_discovery(url, depth, registry_urls=registry_urls, client=client)
    finally:
        if owns_client:
            client.close()

    _cache_insert(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _cache_insert(key: tuple[str, int], result: "DiscoverResult") -> None:
    """Insert result into _CACHE, first purging expired entries and capping at _CACHE_MAX_ENTRIES.

    Args:
        key: Cache key (url, depth).
        result: DiscoverResult to store.
    """
    now = time.monotonic()

    # Purge expired entries.
    expired_keys = [k for k, (_r, expiry) in _CACHE.items() if expiry <= now]
    for k in expired_keys:
        del _CACHE[k]

    # If at or over cap after purge, evict the oldest entry.
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_CACHE))
        del _CACHE[oldest_key]

    _CACHE[key] = (result, now + _CACHE_TTL)


def _run_discovery(
    url: str,
    depth: int,
    *,
    registry_urls: set[str],
    client: httpx.Client,
) -> DiscoverResult:
    """Fetch url, parse feeds, optionally deep-crawl; return a DiscoverResult (never raises).

    Args:
        url: Page URL to fetch.
        depth: 0 = shallow; 1 = deep (probes + section crawl).
        registry_urls: Already-subscribed feed URLs.
        client: Configured httpx.Client.
    """
    outcome = _fetch_html(url, client)
    if outcome.reason_code is not None:
        # Initial fetch failed — map the typed code to a human message.
        msg = _FETCH_REASON_MESSAGES.get(outcome.reason_code, f"Could not fetch {url} as HTML.")
        return DiscoverResult(reason=msg, reason_code=outcome.reason_code)

    # outcome.html and outcome.final_url are guaranteed non-None here.
    html: str = outcome.html  # type: ignore[assignment]
    base_url: str = outcome.final_url  # type: ignore[assignment]
    seen_feed_urls: set[str] = set()
    candidates: list[Candidate] = []

    # --- Shallow tier: declared <link rel=alternate> feeds ---
    declared = parse_declared_feeds(html, base_url)
    _probe_urls(declared, registry_urls, seen_feed_urls, candidates, client)

    # YouTube channel/handle resolution: resolve_feed_url rewrites
    # /channel/UC... or /@handle; returns url unchanged on failure so no spurious candidate.
    resolved = resolve_feed_url(url, client)
    if resolved != url:
        _probe_urls([resolved], registry_urls, seen_feed_urls, candidates, client)

    if depth >= 1:
        # --- Deep tier part 1: probe common paths ---
        origin = _site_origin(base_url)
        common_urls = [urljoin(origin + "/", path.lstrip("/")) for path in _COMMON_FEED_PATHS]
        _probe_urls(common_urls, registry_urls, seen_feed_urls, candidates, client)

        # Deep tier 2: crawl section links one level.  Failed fetches continue — they
        # must NOT override the top-level reason_code (only the initial fetch does that).
        section_links = parse_section_links(html, base_url)
        for section_url in section_links:
            section_outcome = _fetch_html(section_url, client)
            if section_outcome.reason_code is not None:
                continue
            section_html: str = section_outcome.html  # type: ignore[assignment]
            section_base: str = section_outcome.final_url  # type: ignore[assignment]
            section_feeds = parse_declared_feeds(section_html, section_base)
            _probe_urls(section_feeds, registry_urls, seen_feed_urls, candidates, client)

    if candidates:
        return DiscoverResult(candidates=candidates)
    return DiscoverResult(reason="No feeds found on this page.", reason_code="no_feeds")


def _is_bot_challenge(snippet: str) -> bool:
    """Return True if snippet (first ~1KB of body) contains a known bot-challenge marker.

    Args:
        snippet: First ~1KB of the decoded response body.

    Returns:
        True when any _CHALLENGE_MARKERS entry is found (case-insensitive).
    """
    lower = snippet.lower()
    return any(marker in lower for marker in _CHALLENGE_MARKERS)


def _fetch_html(url: str, client: httpx.Client) -> FetchOutcome:
    """Fetch url; return FetchOutcome with reason_code=None on success or a typed failure code.

    Enforces blocked status codes, bot-challenge detection, text/html content-type, and
    the 2MB body cap.  Never raises — all errors are caught and logged.

    Args:
        url: URL to fetch.
        client: Configured httpx.Client.

    Returns:
        FetchOutcome with reason_code in {'blocked','not_html','too_large','http_error','network_error'}
        on failure, or reason_code=None with html+final_url set on success.
    """
    try:
        with client.stream("GET", url) as response:
            status = response.status_code

            # Blocked status codes (403, 429, 503).
            if status in _BLOCKED_STATUS_CODES:
                logger.debug("discovery: blocked (%d) for %s", status, url)
                return FetchOutcome(html=None, final_url=None, reason_code="blocked")

            if status != 200:
                logger.debug("discovery: non-200 %s for %s", status, url)
                return FetchOutcome(html=None, final_url=None, reason_code="http_error")

            content_type = (response.headers.get("content-type") or "").lower()
            if "text/html" not in content_type:
                logger.debug("discovery: non-HTML content-type %r for %s", content_type, url)
                return FetchOutcome(html=None, final_url=None, reason_code="not_html")

            # Read body up to the 2MB cap; discard oversized pages.
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > _MAX_BODY_BYTES:
                    logger.debug(
                        "discovery: oversized body >%d bytes for %s", _MAX_BODY_BYTES, url
                    )
                    return FetchOutcome(html=None, final_url=None, reason_code="too_large")
                chunks.append(chunk)

            # Check the first ~1KB for bot-challenge interstitials (Cloudflare et al.).
            # Performed after buffering so we handle both large and small pages uniformly.
            if chunks:
                snippet = b"".join(chunks)[:1024].decode("utf-8", errors="replace")
                if _is_bot_challenge(snippet):
                    logger.debug("discovery: bot-challenge interstitial detected for %s", url)
                    return FetchOutcome(html=None, final_url=None, reason_code="blocked")

            final_url = str(response.url)
            html = b"".join(chunks).decode("utf-8", errors="replace")
            return FetchOutcome(html=html, final_url=final_url, reason_code=None)

    except httpx.HTTPError as exc:
        logger.debug("discovery: HTTP error fetching %s: %s", url, exc)
        return FetchOutcome(html=None, final_url=None, reason_code="network_error")
    except Exception as exc:  # noqa: BLE001
        logger.debug("discovery: unexpected error fetching %s: %s", url, exc)
        return FetchOutcome(html=None, final_url=None, reason_code="network_error")


def _probe_urls(
    urls: list[str],
    registry_urls: set[str],
    seen: set[str],
    results: list[Candidate],
    client: httpx.Client,
) -> None:
    """Validate each URL as a feed; append deduplicated Candidates to results in place.

    Args:
        urls: Candidate feed URLs to probe.
        registry_urls: Already-subscribed URLs for the already_subscribed flag.
        seen: Dedup guard (mutated here).
        results: Output Candidate list (mutated here).
        client: Retained for API consistency; not used directly by this helper.
    """
    # One temp dir for the entire call; cleaned up in finally to avoid leaks.
    tmp_dir = Path(tempfile.mkdtemp())
    reader_db = tmp_dir / "discover_validate.db"
    try:
        for feed_url in urls:
            if feed_url in seen:
                continue
            seen.add(feed_url)
            try:
                title, kind = _validate_feed(feed_url, reader_db)
            except NotAFeedError:
                logger.debug("discovery: %s did not validate as a feed", feed_url)
                continue
            results.append(
                Candidate(
                    feed_url=feed_url,
                    name=title,
                    kind=kind,
                    already_subscribed=feed_url in registry_urls,
                )
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _site_origin(url: str) -> str:
    """Return scheme+host of url (e.g. 'https://example.com').

    Args:
        url: Any URL string.

    Returns:
        Lowercased scheme+netloc, empty string on failure.
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}".lower()
    except Exception:
        return ""
