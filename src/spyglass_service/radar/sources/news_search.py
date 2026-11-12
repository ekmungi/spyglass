"""News search over Google News RSS (every collection cycle), built from the reader's profile topics.

Google News links are redirects. The real article address is recovered with the
`googlenewsdecoder` package, which makes one network call per link, so it is throttled and
applied only to the newest few unseen results per query. A link that cannot be decoded is kept
as the Google address, which still opens the article in a browser.
"""

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit

import feedparser
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.ingest import store_items
from spyglass_service.models import Item
from spyglass_service.radar import netguard
from spyglass_service.radar.egress import UnsafeQuery, safe_search_query
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE, load_profile
from spyglass_service.radar.sources._common import (
    http_get_bytes,
    item_ids_by_external,
    merge_extras,
    short_hash,
)

logger = logging.getLogger(__name__)

SOURCE = "news"
FEED_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# How many of a query's newest unseen links are resolved to the publisher's address.
DEFAULT_DECODE_LIMIT = 8
# Seconds the decoder waits between article-page fetches, to stay polite to Google.
DECODE_INTERVAL = 1.0
# Seconds between two search queries.
QUERY_PAUSE = 1.0
# Google shows a consent page to clients in the EU and answers the decoder with a redirect to
# it. This cookie is the documented "accepted" marker that skips that page.
_CONSENT_COOKIE = "SOCS=CAI"

# Ordered (keyword in a profile topic name, queries it contributes). These are optional generic
# refinements for the default topics: the reader edits topics, so matching is by keyword, and a
# topic that matches nothing is searched by its own name (see `_own_query`).
TOPIC_QUERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("model release", ("new AI model release", "frontier model launch")),
    ("open-weight", ("open-weight model release",)),
    ("agent", ('"coding agent" OR "agent harness"', '"Model Context Protocol"')),
    ("evaluation", ("AI evaluation benchmark methods",)),
    ("imaging", ("AI medical imaging clinical",)),
    ("regulation", ("AI regulation law policy",)),
    ("science", ("AI scientific discovery research",)),
    ("adoption", ("enterprise AI adoption use cases",)),
)
# Words dropped from a topic's own name before it is searched: they carry no subject, and
# keeping them only narrows an all-words search.
_FUNCTION_WORDS = frozenset(
    {"a", "an", "the", "in", "of", "on", "for", "and", "or", "to", "with", "at", "by", "from"}
)
# A name that leaves this many content words or fewer is searched as one exact phrase, because
# a short name matches best as a phrase; more words are sent as loose terms.
MAX_PHRASE_WORDS = 2
MAX_QUERIES = 14

FetchFn = Callable[[str], bytes]
DecodeFn = Callable[[list[str]], list[str | None]]


def _own_query(name: str) -> str:
    """A search query built from a topic's own text, for a topic with no refinement entry.

    A parenthetical aside is dropped, the rest is split into words, and common function words
    are removed (casing of the remaining words is kept). One or two content words are quoted as
    a phrase; more are sent as loose terms, which the news search treats as "all of these
    words". A name with no content word left is returned as the cleaned name.

    Args:
        name: The topic's name as the reader wrote it.

    Returns:
        The search query; an empty string for an empty name.
    """
    core = re.sub(r"\s*\([^)]*\)", "", name).strip() or name.strip()
    words = [w for w in (raw.strip(',;:"') for raw in core.split()) if re.search(r"[^\W\d_]", w)]
    content = [w for w in words if w.lower() not in _FUNCTION_WORDS]
    if not content:
        return core
    query = " ".join(content)
    return f'"{query}"' if len(content) <= MAX_PHRASE_WORDS else query


def topic_queries(profile: dict | None = None) -> list[str]:
    """The news queries for a reader profile: one or two searches per topic, at most 14.

    Args:
        profile: A profile document (as `load_profile` returns); the default profile when None.

    Returns:
        De-duplicated queries in topic order, capped at 14. A topic whose name matches none
        of the refinement keywords contributes a query built from its own name.
    """
    topics = (profile or DEFAULT_PROFILE).get("topics") or []
    queries: list[str] = []
    for topic in topics:
        name = str(topic.get("name", "")).strip()
        if not name:
            continue
        lowered = name.lower()
        matched = [qs for key, qs in TOPIC_QUERIES if key in lowered]
        for query in (q for qs in matched for q in qs) if matched else [_own_query(name)]:
            if query not in queries:
                queries.append(query)
    return queries[:MAX_QUERIES]


def decode_google_urls(links: list[str]) -> list[str | None]:
    """Resolve Google News redirect links to publisher addresses; None where that fails.

    One batch call: article pages are fetched one by one (throttled), then a single POST
    resolves them all. Any error leaves every link unresolved rather than raising.
    """
    if not links:
        return []
    # The decoder makes its own requests (with a consent cookie, so it cannot use the guarded
    # client); it is only ever given links on Google's own news host.
    own = [(urlsplit(link).hostname or "").lower() == "news.google.com" for link in links]
    if not all(own):
        kept = iter(decode_google_urls([link for link, ok in zip(links, own) if ok]))
        return [next(kept) if ok else None for ok in own]
    try:
        from googlenewsdecoder import GoogleDecoder
    except ImportError:
        logger.warning("googlenewsdecoder is not installed; keeping Google News links")
        return [None] * len(links)
    try:
        with GoogleDecoder(timeout=15) as decoder:
            decoder.client.headers["Cookie"] = _CONSENT_COOKIE
            results = decoder.decode_google_news_urls(links, interval=DECODE_INTERVAL)
    except Exception:  # noqa: BLE001 -- a decoder failure must never fail the collection
        logger.exception("Google News link decoding failed; keeping Google links")
        return [None] * len(links)
    decoded: list[str | None] = []
    for result in results:
        url = result.get("decoded_url") if result.get("success") else None
        # The answer becomes an item address that is fetched later: only public http(s) addresses.
        decoded.append(url if isinstance(url, str) and netguard.is_public_url(url) else None)
    return decoded


def _clean_title(title: str, publisher: str | None) -> str:
    """Drop the trailing " - Publisher" Google appends to every headline."""
    title = title.strip()
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].rstrip()
    head, sep, tail = title.rpartition(" - ")
    # Without a <source> name, only strip a short tail that looks like a publication name.
    return head.rstrip() if sep and head and len(tail) <= 40 else title


def _published(entry) -> datetime | None:
    """Publication time of a feed entry as an aware UTC datetime, or None."""
    raw = entry.get("published")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _stable_id(link: str) -> str:
    """External id from a Google link; the query string varies between requests."""
    return "gn-" + short_hash(link.split("?", 1)[0])


def search_news(
    query: str,
    days: int = 2,
    *,
    fetch: FetchFn | None = None,
    decode: DecodeFn | None = None,
    decode_limit: int = DEFAULT_DECODE_LIMIT,
    known_ids: set[str] | None = None,
) -> list[CollectedItem]:
    """Search Google News for `query` over the last `days` days.

    Args:
        query: The search text (Google operators such as OR and quotes work).
        days: Look-back window in days.
        fetch: Callable returning the feed bytes for a URL; an HTTP GET by default.
        decode: Callable resolving Google links to publisher links; the real decoder by default.
        decode_limit: At most this many of the newest unseen results are decoded.
        known_ids: External ids already stored; those are returned but never decoded again.

    Returns:
        One CollectedItem per result, newest first, source "news", origin the publisher.
    """
    # Search text can come from model suggestions (watch discovery, follow suggestions), so it is
    # checked before it is sent: one line, at most 200 characters, no web address inside. It is
    # only ever sent as the `q` parameter of the fixed search address.
    try:
        query = safe_search_query(query)
    except UnsafeQuery as exc:
        logger.warning("news query refused: %s", exc)
        return []
    url = FEED_URL.format(q=quote_plus(f"{query} when:{max(1, days)}d"))
    parsed = feedparser.parse((fetch or http_get_bytes)(url))
    rows = []
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        publisher = (entry.get("source") or {}).get("title")
        rows.append((entry, link, publisher))
    rows.sort(key=lambda row: _published(row[0]) or datetime.min.replace(tzinfo=UTC),
              reverse=True)

    known = known_ids or set()
    to_decode = [row[1] for row in rows if _stable_id(row[1]) not in known][:decode_limit]
    resolved = dict(zip(to_decode, (decode or decode_google_urls)(to_decode), strict=False))

    items = []
    for entry, link, publisher in rows:
        items.append(
            CollectedItem(
                source=SOURCE,
                external_id=_stable_id(link),
                title=_clean_title(entry.get("title") or link, publisher),
                url=resolved.get(link) or link,
                source_tags=[f"query:{query}"],
                published_at=_published(entry),
                origin=publisher,
            )
        )
    return items


def _known_news_ids(engine: Engine) -> set[str]:
    """External ids of the news items already stored."""
    with Session(engine) as session:
        return set(session.exec(select(Item.external_id).where(Item.source == SOURCE)).all())


def collect_news(
    engine: Engine,
    settings: Settings,
    *,
    fetch: FetchFn | None = None,
    decode: DecodeFn | None = None,
    queries: list[str] | None = None,
    days: int = 2,
    pause: float = QUERY_PAUSE,
) -> int:
    """Run every topic query, store the results and record publisher and query as extras.

    A failing query is logged and skipped so one bad search never loses the others.

    Returns:
        The number of new items stored.
    """
    from spyglass_service.radar import tracks  # the followed subjects' queries join the cycle

    cycle = queries is None
    if queries is None:
        with Session(engine) as session:
            topics = topic_queries(load_profile(session))
        queries = tracks.merge_queries(tracks.active_queries(engine), topics)
    known = _known_news_ids(engine)
    known_before = set(known)
    collected: list[CollectedItem] = []
    failures = 0
    ran: set[str] = set()
    new_by_query: dict[str, int] = {}
    for index, query in enumerate(queries):
        if index and pause:
            time.sleep(pause)
        try:
            found = search_news(query, days, fetch=fetch, decode=decode, known_ids=known)
        except Exception:  # noqa: BLE001 -- isolate each query
            failures += 1
            logger.exception("news query failed: %s", query)
            continue
        ran.add(query)
        new_by_query[query] = len({i.external_id for i in found} - known)
        known.update(item.external_id for item in found)
        collected.extend(found)
    if failures and failures == len(queries):
        raise RuntimeError(f"all {failures} news queries failed")
    new = store_items(engine, collected)
    ids = item_ids_by_external(engine, SOURCE, [i.external_id for i in collected])
    extras = {
        ids[i.external_id]: {
            "publisher": i.origin,
            "query": (i.source_tags[0].removeprefix("query:") if i.source_tags else None),
        }
        # Reversed so the first query to find an item is the one recorded (tracks run first).
        for i in reversed(collected)
        if i.external_id in ids and i.external_id not in known_before
    }
    merge_extras(engine, extras)
    if cycle:
        tracks.record_runs(engine, ran, new_by_query)
    return new
