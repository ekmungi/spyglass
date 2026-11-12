"""News search for the watch: the shared search when it exists, else a small Google News RSS one.

`default_search()` returns a callable `(query, days=...) -> list[CollectedItem]`. It prefers
`radar.sources.news_search.search_news` and falls back to the private implementation below, so
the watch keeps working while the shared module is absent or fails to import.
"""

import calendar
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import quote

import feedparser

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

SearchFn = Callable[..., list[CollectedItem]]
FetchFn = Callable[[str], str]

_RSS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _http_fetch(url: str) -> str:
    """GET a URL and return its text; raises httpx.HTTPError on failure."""
    # The guarded client allows public addresses only and sends the generic agent.
    with netguard.page_client(timeout=20.0) as client:
        response = client.get(url)
    response.raise_for_status()
    return response.text


def _published(entry) -> datetime | None:
    """The entry's publication time as naive UTC, or None."""
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC).replace(tzinfo=None)


def search_news(
    query: str, *, days: int = 7, limit: int = 30, fetch: FetchFn | None = None
) -> list[CollectedItem]:
    """Search Google News RSS for `query` over the last `days` days; returns up to `limit` items.

    fetch: `(url) -> text`, injectable for tests. Network errors propagate to the caller, which
    decides whether one failed search should stop a whole sweep.
    """
    url = _RSS_URL.format(q=quote(f"{query} when:{max(1, days)}d"))
    feed = feedparser.parse((fetch or _http_fetch)(url))
    items: list[CollectedItem] = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        if not title or not link:
            continue
        publisher = ((entry.get("source") or {}).get("title") or "").strip()
        # Google appends " - Publisher" to every headline; keep the headline alone.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].rstrip()
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")
        items.append(
            CollectedItem(
                source="news",
                external_id=entry.get("id") or link,
                title=title,
                url=link,
                summary=" ".join(summary.split()) or None,
                published_at=_published(entry),
                origin=publisher or None,
            )
        )
    return items


def _as_collected(obj) -> CollectedItem | None:
    """Coerce a result of the shared search (an item or a dict) into a CollectedItem, or None."""
    if isinstance(obj, CollectedItem):
        return obj
    get = obj.get if isinstance(obj, dict) else lambda k, d=None: getattr(obj, k, d)
    title, url = get("title"), get("url")
    if not title or not url:
        return None
    return CollectedItem(
        source=get("source") or "news", external_id=str(get("external_id") or url), title=str(title),
        url=str(url), summary=get("summary"), published_at=get("published_at"), origin=get("origin"),
    )


def default_search(decode_limit: int | None = None) -> SearchFn:
    """The shared news search when importable, otherwise the fallback in this module.

    decode_limit: passed to the shared search, which resolves Google redirect links one network
        call each; 0 skips that (enough when only headlines are read). None keeps its default.
    """
    try:
        from spyglass_service.radar.sources.news_search import search_news as shared
    except ImportError:
        return search_news

    def call(query: str, *, days: int = 7, **_: object) -> list[CollectedItem]:
        """Run the shared search and normalise its results."""
        extra = {} if decode_limit is None else {"decode_limit": decode_limit}
        results = shared(query, days=days, **extra)
        return [c for c in (_as_collected(r) for r in results) if c is not None]

    return call
