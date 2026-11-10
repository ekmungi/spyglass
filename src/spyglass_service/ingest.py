"""Ingestion: store collected items with (source, external_id) deduplication."""

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.models import Item, Tombstone


def store_items(engine: Engine, collected: list[CollectedItem]) -> int:
    """Insert items not yet in the database; return how many were new.

    Existing rows are never modified: the raw item is immutable history, and
    re-fetches of the same (source, external_id) are simply skipped.
    Tombstoned (source, external_id) pairs are also skipped so deleted items
    are never re-collected.
    """
    new_count = 0
    with Session(engine) as session:
        existing = set(
            session.exec(select(Item.source, Item.external_id)).all()
        )
        tombstoned = set(
            session.exec(select(Tombstone.source, Tombstone.external_id)).all()
        )
        for item in collected:
            if (item.source, item.external_id) in existing:
                continue
            if (item.source, item.external_id) in tombstoned:
                continue
            existing.add((item.source, item.external_id))
            session.add(
                Item(
                    source=item.source,
                    external_id=item.external_id,
                    title=item.title,
                    url=item.url,
                    summary=item.summary,
                    source_tags=",".join(item.source_tags) or None,
                    origin=item.origin,
                    published_at=item.published_at,
                    feed_url=item.feed_url,
                )
            )
            new_count += 1
        session.commit()
    return new_count
