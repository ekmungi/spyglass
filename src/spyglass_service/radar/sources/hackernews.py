"""Hacker News stories with a community signal, read from the Algolia search API.

Two searches run: everything above a high point threshold (the general front page), and AI
related stories above a lower threshold. Points and the discussion link are kept as item extras
and refreshed on every run, because a story's score keeps moving after it is first collected.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.ingest import store_items
from spyglass_service.radar.sources._common import (
    http_get_bytes,
    host_of,
    item_ids_by_external,
    merge_extras,
)

logger = logging.getLogger(__name__)

SOURCE = "hn"
API_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://news.ycombinator.com/item?id={id}"
MIN_POINTS = 100
# AI stories are rarer on the front page, so they get a lower bar.
AI_MIN_POINTS = 50
AI_QUERY = "AI OR LLM OR GPT OR Claude OR agents OR OpenAI OR Anthropic OR model"
PAGE_SIZE = 50

# (url, params) -> response bytes
FetchFn = Callable[[str, dict], bytes]


def _default_fetch(url: str, params: dict) -> bytes:
    """GET the Algolia API with query parameters."""
    return http_get_bytes(url, params)


def parse_hits(payload: dict) -> list[dict]:
    """Turn an Algolia response into plain story dicts, skipping malformed hits.

    Each dict has: id, title, url, points, comments, comments_url, created (aware UTC datetime).
    A text post (no link) uses the Hacker News item page as its url.
    """
    stories = []
    for hit in payload.get("hits", []):
        story_id = str(hit.get("objectID") or "")
        title = (hit.get("title") or "").strip()
        if not story_id or not title:
            continue
        comments_url = ITEM_URL.format(id=story_id)
        created = hit.get("created_at_i")
        stories.append(
            {
                "id": story_id,
                "title": title,
                "url": hit.get("url") or comments_url,
                "points": int(hit.get("points") or 0),
                "comments": int(hit.get("num_comments") or 0),
                "comments_url": comments_url,
                "created": datetime.fromtimestamp(created, UTC) if created else None,
            }
        )
    return stories


def fetch_stories(
    days: int = 2, *, fetch: FetchFn | None = None, now: float | None = None
) -> list[dict]:
    """The recent high-signal stories (both searches), de-duplicated, highest points first."""
    fetch = fetch or _default_fetch
    since = int((now if now is not None else time.time()) - days * 86400)
    searches = (
        {"numericFilters": f"created_at_i>{since},points>{MIN_POINTS}"},
        {"numericFilters": f"created_at_i>{since},points>{AI_MIN_POINTS}", "query": AI_QUERY},
    )
    by_id: dict[str, dict] = {}
    errors = 0
    for extra in searches:
        params = {"tags": "story", "hitsPerPage": PAGE_SIZE, **extra}
        try:
            payload = json.loads(fetch(API_URL, params))
        except (ValueError, OSError) as exc:
            errors += 1
            logger.warning("Hacker News search failed: %s", exc)
            continue
        for story in parse_hits(payload):
            by_id.setdefault(story["id"], story)
    if errors == len(searches):
        raise RuntimeError("Hacker News API unreachable")
    return sorted(by_id.values(), key=lambda s: s["points"], reverse=True)


def to_items(stories: list[dict]) -> list[CollectedItem]:
    """Normalise stories into collected items (origin is the linked site)."""
    return [
        CollectedItem(
            source=SOURCE,
            external_id=s["id"],
            title=s["title"],
            url=s["url"],
            published_at=s["created"],
            origin=host_of(s["url"]) if s["url"] != s["comments_url"] else "Hacker News",
        )
        for s in stories
    ]


def collect_hackernews(
    engine: Engine, settings: Settings, *, fetch: FetchFn | None = None, days: int = 2
) -> int:
    """Store new stories and refresh points on every story seen, new or old.

    Returns:
        The number of new items stored.
    """
    stories = fetch_stories(days, fetch=fetch)
    new = store_items(engine, to_items(stories))
    ids = item_ids_by_external(engine, SOURCE, [s["id"] for s in stories])
    merge_extras(
        engine,
        {
            ids[s["id"]]: {
                "points": s["points"],
                "comments": s["comments"],
                "comments_url": s["comments_url"],
            }
            for s in stories
            if s["id"] in ids
        },
    )
    return new
