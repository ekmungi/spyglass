"""Tests for storing collected items with deduplication."""

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.ingest import store_items
from spyglass_service.lifecycle import add_tombstone
from spyglass_service.models import Item


def make_item(ext_id: str, source: str = "rss") -> CollectedItem:
    """Helper: minimal collected item with a controllable identity."""
    return CollectedItem(
        source=source,
        external_id=ext_id,
        title=f"Title {ext_id}",
        url=f"https://example.test/{ext_id}",
        summary="s",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
    )


def test_new_items_are_stored_and_counted(tmp_path: Path) -> None:
    """Fresh items are inserted; the count of new rows comes back."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    new_count = store_items(engine, [make_item("a"), make_item("b")])
    assert new_count == 2


def test_refetched_items_do_not_duplicate(tmp_path: Path) -> None:
    """Storing the same (source, external_id) twice keeps exactly one row."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    store_items(engine, [make_item("a")])
    new_count = store_items(engine, [make_item("a"), make_item("b")])
    with Session(engine) as session:
        rows = session.exec(select(Item)).all()
    assert new_count == 1
    assert len(rows) == 2


def test_same_external_id_from_different_sources_both_stored(tmp_path: Path) -> None:
    """Identity is (source, external_id) -- not external_id alone."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    count = store_items(engine, [make_item("x", source="rss"), make_item("x", source="raindrop")])
    assert count == 2


def make_engine(tmp_path: Path):
    """Helper: create and initialise a fresh in-memory-equivalent test database."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def test_store_items_skips_tombstoned(tmp_path: Path) -> None:
    """A tombstoned (source, external_id) is not re-inserted by store_items."""
    engine = make_engine(tmp_path)
    add_tombstone(engine, "rss", "x")
    item = CollectedItem(source="rss", external_id="x", title="T", url="https://x.test")
    new_count = store_items(engine, [item])
    assert new_count == 0
    with Session(engine) as session:
        rows = session.exec(select(Item)).all()
    assert len(rows) == 0


def test_store_items_still_inserts_untombstoned(tmp_path: Path) -> None:
    """A different external_id that is not tombstoned is inserted normally."""
    engine = make_engine(tmp_path)
    add_tombstone(engine, "rss", "x")
    item = CollectedItem(source="rss", external_id="y", title="T", url="https://y.test")
    new_count = store_items(engine, [item])
    assert new_count == 1
    with Session(engine) as session:
        rows = session.exec(select(Item)).all()
    assert len(rows) == 1
