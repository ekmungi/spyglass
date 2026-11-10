"""Build the active collector set from the Feed registry."""

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.collectors.base import Collector
from spyglass_service.collectors.raindrop import RaindropCollector
from spyglass_service.collectors.rss import RssCollector
from spyglass_service.config import Settings
from spyglass_service.feed_registry import list_feeds, seed_from_note


def build_collectors(settings: Settings, engine: Engine) -> list[Collector]:
    """Return one collector per configured source; unconfigured sources are skipped.

    On the first call the feed note (if present) is seeded into the registry so
    the old hand-edited note continues to work without manual migration.  After
    that seed_from_note is a no-op (guard: registry is non-empty).

    Only *enabled* Feed rows contribute to the RSS collector; disabled rows are
    silently ignored so the user can pause a feed without losing its history.

    Args:
        settings: Runtime settings (data_dir, raindrop_token, feed_note_path).
        engine: SQLAlchemy engine connected to the Spyglass database.

    Returns:
        List of configured Collector instances (may be empty).
    """
    collectors: list[Collector] = []

    with Session(engine) as session:
        # One-time migration: if the registry is empty and a note exists, seed it.
        seed_from_note(settings, session)

        feed_urls = [f.feed_url for f in list_feeds(session) if f.enabled]

    if feed_urls:
        collectors.append(
            RssCollector(feed_urls=feed_urls, reader_db_path=settings.data_dir / "reader.db")
        )

    if settings.raindrop_token:
        collectors.append(RaindropCollector(token=settings.raindrop_token))

    return collectors
