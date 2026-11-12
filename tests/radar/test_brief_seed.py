"""Shared helpers that build small databases and indexes for the brief, watch and papers tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, ItemExtra, ItemState, dumps

# A fixed "now" so every test is independent of the wall clock (naive UTC, as stored).
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
NOW_NAIVE = NOW.replace(tzinfo=None)


def make_engine(tmp_path: Path) -> Engine:
    """A fresh database with every table created."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def hours_ago(hours: float) -> datetime:
    """Naive-UTC time `hours` before NOW."""
    return NOW_NAIVE - timedelta(hours=hours)


def add_item(
    engine: Engine,
    title: str,
    *,
    score: int | None = 70,
    tier: str = "top",
    section: str = "health",
    kind: str = "news",
    event_key: str | None = None,
    origin: str = "Example Daily",
    age_hours: float = 3,
    source: str = "rss",
    from_user: bool = False,
    hidden: bool = False,
    headline: str | None = None,
    why: str | None = "Matters for the reader.",
    entities: list[str] | None = None,
    upvotes: int | None = None,
    arxiv_id: str | None = None,
    url: str | None = None,
    summary: str | None = None,
    published: bool = True,
) -> int:
    """Insert an item (and, when score is not None, its assessment); return the item id."""
    with Session(engine) as session:
        when = hours_ago(age_hours)
        item = Item(
            source=source,
            external_id=f"{title}-{age_hours}-{origin}",
            title=title,
            url=url or f"https://example.com/{abs(hash(title)) % 10**8}",
            summary=summary,
            origin=origin,
            published_at=when if published else None,
            fetched_at=when,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        if score is not None:
            session.add(
                Assessment(
                    item_id=item.id, stage="digest", score=score, tier=tier, section=section,
                    kind=kind, headline=headline, why=why, event_key=event_key,
                    entities=dumps(entities) if entities is not None else None,
                )
            )
        if from_user or hidden:
            session.add(ItemState(item_id=item.id, from_user=from_user, hidden=hidden))
        extra = {}
        if upvotes is not None:
            extra["upvotes"] = upvotes
        if arxiv_id:
            extra["arxiv_id"] = arxiv_id
        if extra:
            session.add(ItemExtra(item_id=item.id, data=dumps(extra)))
        session.commit()
        return item.id


def make_index(vectors: dict[int, list[float]]) -> EmbeddingIndex:
    """A 4-dimensional index holding the given (normalised on the way in) vectors."""
    index = EmbeddingIndex(lambda texts: np.ones((len(texts), 4), dtype=np.float32), "fake", 4)
    for item_id, vec in vectors.items():
        v = np.array(vec, dtype=np.float32)
        index.add(item_id, (v / np.linalg.norm(v)).tobytes())
    return index
