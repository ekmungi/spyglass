"""Collector contract: any source plugs in by satisfying this protocol."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CollectedItem:
    """One item fetched from a source, normalized for ingestion.

    (source, external_id) is the dedupe identity; everything else is display data.
    """

    source: str
    external_id: str
    title: str
    url: str
    summary: str | None = None
    source_tags: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    # Where the item actually came from: the feed title (RSS) or site domain
    # (Raindrop). The `source` field only names the collector.
    origin: str | None = None
    # Durable feed key: the resolved feed URL (RSS only; None for Raindrop / other sources).
    # Feed.feed_url == Item.feed_url is the join used by the feeds-tab endpoint.
    feed_url: str | None = None


@runtime_checkable
class Collector(Protocol):
    """Anything with a name and a collect() yielding normalized items is a source."""

    name: str

    def collect(self) -> list[CollectedItem]:
        """Fetch and return new-or-current items; raise on hard source failure."""
        ...
