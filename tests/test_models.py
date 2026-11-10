"""Tests for the SQLModel schema: items, cards, run logs, and feeds."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from spyglass_service.models import Card, CardState, Feed, Item, RunLog


def test_card_states_cover_the_triage_lifecycle() -> None:
    """The five card states from the design: new, reviewed, dismissed, queued, finished."""
    expected = {"new", "reviewed", "dismissed", "queued", "finished"}
    assert {state.value for state in CardState} == expected


def test_item_carries_source_identity_for_dedupe() -> None:
    """An item is identified by (source, external_id) so re-fetches never duplicate."""
    item = Item(source="rss", external_id="abc-123", title="A paper", url="https://x.test/p")
    assert (item.source, item.external_id) == ("rss", "abc-123")


def test_new_card_defaults_to_state_new_with_no_note() -> None:
    """Cards enter the dashboard as state 'new'; notes are attached later by the user."""
    card = Card(item_id=1, summary="why this matters")
    assert card.state == CardState.NEW
    assert card.note is None


def test_run_log_records_source_and_outcome() -> None:
    """Activity-tab rows: which source ran and whether it succeeded."""
    run = RunLog(source="raindrop", status="ok", detail="14 new items")
    assert run.status == "ok"
    assert run.started_at is not None


# ---------------------------------------------------------------------------
# Feed model tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_engine():
    """In-memory SQLite engine with all tables created (no file I/O)."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_feed_table_is_created_by_metadata(mem_engine) -> None:
    """The Feed table exists after create_all so init_db brings it up on a fresh DB."""
    with Session(mem_engine) as session:
        from sqlalchemy import text
        tables = {r[0] for r in session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
    assert "feed" in tables


def test_feed_defaults_are_applied() -> None:
    """enabled defaults True, name_overridden defaults False, nullable fields default None."""
    feed = Feed(feed_url="https://example.com/feed.rss", name="Example", kind="rss", added_via="manual")
    assert feed.enabled is True
    assert feed.name_overridden is False
    assert feed.last_fetch_status is None
    assert feed.last_fetch_at is None
    assert feed.last_error is None
    assert feed.created_at is not None
    assert feed.updated_at is not None


def test_feed_url_uniqueness_is_enforced(mem_engine) -> None:
    """Two Feed rows with the same feed_url must raise IntegrityError (UNIQUE constraint)."""
    with Session(mem_engine) as session:
        session.add(Feed(feed_url="https://example.com/feed.rss", name="A", kind="rss", added_via="manual"))
        session.commit()
    with Session(mem_engine) as session:
        session.add(Feed(feed_url="https://example.com/feed.rss", name="B", kind="rss", added_via="manual"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_item_feed_url_defaults_to_none() -> None:
    """Non-RSS items (Raindrop) leave feed_url null; default must be None."""
    item = Item(source="raindrop", external_id="rd-1", title="A link", url="https://x.test/link")
    assert item.feed_url is None


# ---------------------------------------------------------------------------
# Brief model tests
# ---------------------------------------------------------------------------


def test_brief_roundtrips(mem_engine) -> None:
    """A Brief row persists and reads back with all its fields intact."""
    from datetime import UTC, datetime

    from spyglass_service.models import Brief

    covers_from = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    covers_until = datetime(2026, 7, 2, 8, 0, tzinfo=UTC)
    with Session(mem_engine) as session:
        brief = Brief(
            covers_from=covers_from,
            covers_until=covers_until,
            markdown="# Daily Brief\n\nBody.",
            item_count=3,
            low_count=1,
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        bid = brief.id
    with Session(mem_engine) as session:
        stored = session.get(Brief, bid)
    assert stored is not None
    assert stored.markdown == "# Daily Brief\n\nBody."
    assert stored.item_count == 3
    assert stored.low_count == 1
    assert stored.created_at is not None
    # SQLite stores naive datetimes; compare the wall-clock values.
    assert stored.covers_from.replace(tzinfo=None) == covers_from.replace(tzinfo=None)
    assert stored.covers_until.replace(tzinfo=None) == covers_until.replace(tzinfo=None)


def test_card_brief_id_defaults_to_none() -> None:
    """New cards are un-briefed until a compose pass stamps them."""
    card = Card(item_id=1, summary="s")
    assert card.brief_id is None


def test_item_feed_url_can_be_set() -> None:
    """RSS items carry the canonical feed_url so the Feed table can be joined."""
    item = Item(
        source="rss",
        external_id="rss-1",
        title="An article",
        url="https://example.com/article",
        feed_url="https://example.com/feed.rss",
    )
    assert item.feed_url == "https://example.com/feed.rss"
