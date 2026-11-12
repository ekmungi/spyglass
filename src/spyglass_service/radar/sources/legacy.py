"""The engine's own collectors (feeds and Raindrop), run the way the radar needs them.

Two differences from the plain refresh: a new feed with a long archive (some publish over a
thousand posts) must not flood the database with old items, and a feed the reader switched
off must really stop adding items (the reader library keeps fetching every feed it has ever
been given, so the registry's "enabled" flag is applied here).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.collectors.base import Collector, CollectedItem
from spyglass_service.collectors.factory import build_collectors
from spyglass_service.collectors.rss import RssCollector
from spyglass_service.config import Settings
from spyglass_service.feed_registry import list_feeds
from spyglass_service.refresh import run_refresh

logger = logging.getLogger(__name__)

# Items published longer ago than this are not stored from a feed. Items without a date are kept.
MAX_AGE_DAYS = 21


class RecentRssCollector(RssCollector):
    """An RssCollector that drops old entries and entries of feeds that are switched off."""

    def __init__(self, base: RssCollector, enabled_urls: set[str], max_age_days: int) -> None:
        super().__init__(feed_urls=base._feed_urls, reader_db_path=base._db_path)
        self._enabled = enabled_urls
        self._max_age = timedelta(days=max_age_days)

    def collect(self) -> list[CollectedItem]:
        """Collect as RssCollector does, then keep only recent entries of enabled feeds."""
        cutoff = datetime.now(UTC) - self._max_age
        kept = []
        for item in super().collect():
            if item.feed_url and item.feed_url not in self._enabled:
                continue
            published = item.published_at
            if published is not None:
                published = published if published.tzinfo else published.replace(tzinfo=UTC)
                if published < cutoff:
                    continue
            kept.append(item)
        return kept


def build_legacy_collectors(
    settings: Settings, engine: Engine, max_age_days: int = MAX_AGE_DAYS
) -> list[Collector]:
    """The feed and Raindrop collectors, with the feed collector wrapped as described above."""
    collectors = build_collectors(settings, engine)
    with Session(engine) as session:
        enabled = {f.feed_url for f in list_feeds(session) if f.enabled}
    return [
        RecentRssCollector(c, enabled, max_age_days) if isinstance(c, RssCollector) else c
        for c in collectors
    ]


def run_legacy_collection(engine: Engine, settings: Settings) -> int:
    """Run the feed and Raindrop collectors; returns the number of new items stored."""
    return run_refresh(engine, build_legacy_collectors(settings, engine))
