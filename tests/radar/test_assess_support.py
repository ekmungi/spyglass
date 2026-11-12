"""Shared helpers for the assessment, pipeline and profile tests: a throwaway database, settings
that never read the real environment file, item factories and a scripted fake model.
(No tests live here.)"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, Feed, InboxEntry, Item
from spyglass_service.radar.models import ItemState

_ids = count(1)
# "Now" for test items, as naive UTC like SQLite stores it: one hour ago, so items fall inside
# the pipeline's default recent-items window whenever the tests run.
BASE_TIME = datetime.now(UTC).replace(tzinfo=None, microsecond=0) - timedelta(hours=1)


def make_engine(tmp_path: Path) -> Engine:
    """A fresh database with every table; the caller must dispose it."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings that ignore the repository's `.env` (so no real key is ever loaded)."""
    values = {"data_dir": tmp_path, "radar_digest_gate": 50,
              "radar_triage_model": "triage-model", "radar_digest_model": "digest-model"}
    return Settings(_env_file=None, **{**values, **overrides})


def add_item(engine: Engine, title: str = "An item about AI in endoscopy", *,
             source: str = "rss", feed_url: str | None = None, summary: str = "A short summary.",
             age_hours: float = 0, published: bool = True, origin: str | None = "A Journal") -> int:
    """Insert an Item (and the Card the older app keeps beside it); return the item id."""
    n = next(_ids)
    when = BASE_TIME - timedelta(hours=age_hours)
    with Session(engine) as session:
        item = Item(source=source, external_id=f"x{n}", title=title, url=f"https://example.org/{n}",
                    summary=summary, origin=origin, feed_url=feed_url,
                    published_at=when if published else None, fetched_at=when)
        session.add(item)
        session.commit()
        session.refresh(item)
        session.add(Card(item_id=item.id, summary=""))
        session.commit()
        return item.id


def set_feedback(engine: Engine, item_id: int, feedback: str, at: datetime | None = None) -> None:
    """Give an item the older app's thumbs-up ("up") or thumbs-down ("down")."""
    with Session(engine) as session:
        row = session.exec(select(Card).where(Card.item_id == item_id)).one()
        row.feedback, row.feedback_at = feedback, at or BASE_TIME
        session.add(row)
        session.commit()


def set_state(engine: Engine, item_id: int, **fields) -> None:
    """Create or update the item's ItemState with `fields`."""
    with Session(engine) as session:
        row = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
        row = row or ItemState(item_id=item_id)
        for name, value in fields.items():
            setattr(row, name, value)
        session.add(row)
        session.commit()


def add_feed(engine: Engine, url: str, *, enabled: bool) -> None:
    """Register a feed, switched on or off."""
    with Session(engine) as session:
        session.add(Feed(feed_url=url, name=url, kind="rss", enabled=enabled, added_via="test"))
        session.commit()


def add_inbox_entry(engine: Engine, item_id: int) -> None:
    """Record that the item arrived through the Slack inbox."""
    with Session(engine) as session:
        card = session.exec(select(Card).where(Card.item_id == item_id)).one()
        session.add(InboxEntry(card_id=card.id))
        session.commit()


def store_text(engine: Engine, item_id: int, text: str = "Full text. " * 50) -> None:
    """Store readable full text for an item, as the reader package would."""
    content_store.store_fulltext(engine, item_id=item_id, markdown=text, status="ok")


def ids_in(messages: list[dict]) -> list[int]:
    """The item ids of a triage request, read from its user message."""
    lines = messages[-1]["content"].splitlines()[1:]
    return [json.loads(line)["id"] for line in lines if line.strip()]


DIGEST_REPLY = {
    "key_points": ["Point one with 42 cases.", "Point two.", "Point three."],
    "entities": ["Olympus", "FDA"],
    "headline": "FDA clears Olympus polyp detector for colonoscopy",
    "why": "You can compare this clearance with your own submission plan.",
    "event_key": "FDA Clears Olympus Polyp AI!",
    "section": "health",
    "kind": "regulatory",
    "score": 88,
}


class FakeLlm:
    """A scripted model: triage scores come from `score_for(id)`, digests from `digest`.

    Records every call as (schema name, messages, model). `hook(call_number, schema_name,
    messages)` may raise, or return a reply that replaces the scripted one (None keeps it).
    """

    def __init__(self, score_for: Callable[[int], int] = lambda _i: 70,
                 digest: dict | None = None,
                 hook: Callable[[int, str, list[dict]], object] | None = None) -> None:
        """Set the scoring rule, the digest reply and an optional per-call override."""
        self.score_for = score_for
        self.digest = dict(DIGEST_REPLY if digest is None else digest)
        self.hook = hook
        self.calls: list[tuple[str, list[dict], str]] = []

    def __call__(self, messages: list[dict], schema: dict, model: str) -> dict:
        """Answer one request (or let the hook replace the answer or raise)."""
        self.calls.append((schema["name"], messages, model))
        if self.hook is not None:
            override = self.hook(len(self.calls), schema["name"], messages)
            if override is not None:
                return override
        if schema["name"] == "triage":
            return {"items": [{"id": i, "reason": "fits", "score": self.score_for(i),
                               "section": "health", "kind": "news"} for i in ids_in(messages)]}
        return dict(self.digest)

    def count(self, name: str) -> int:
        """How many calls used the schema `name`."""
        return sum(1 for call in self.calls if call[0] == name)


def utc(dt: datetime) -> datetime:
    """`dt` marked as UTC."""
    return dt.replace(tzinfo=UTC)
