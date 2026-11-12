"""Tests for card lifecycle teardown: archive / unarchive + the Raindrop cascade."""

from pathlib import Path

import httpx
from sqlalchemy import text
from sqlmodel import Session, select

from spyglass_service.cards import materialize_cards
from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.content_store import store_fulltext
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.highlights import add_highlight
from spyglass_service.ingest import store_items
from spyglass_service.lifecycle import (
    add_tombstone,
    archive_cards,
    cascade_raindrop_removal,
    delete_cards,
    unarchive_cards,
)
from spyglass_service.models import Card, CardState, Content, Highlight, Item, Tombstone


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def make_settings(tmp_path: Path, token: str | None = "tok") -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", raindrop_token=token)


def add_card(engine, source: str, ext_id: str) -> int:
    """Add an item, materialize its raw card, and return the card_id."""
    with Session(engine) as session:
        item = Item(source=source, external_id=ext_id, title=f"T {ext_id}", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
    materialize_cards(engine)
    with Session(engine) as session:
        return session.exec(select(Card).where(Card.item_id == item_id)).one().id


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_archive_cards_sets_dismissed(tmp_path: Path) -> None:
    """Archiving flips cards to the DISMISSED ('archived, never deleted') state."""
    engine = make_engine(tmp_path)
    c1, c2 = add_card(engine, "rss", "a"), add_card(engine, "rss", "b")
    assert archive_cards(engine, [c1, c2]) == 2
    with Session(engine) as s:
        assert s.get(Card, c1).state == CardState.DISMISSED
        assert s.get(Card, c2).state == CardState.DISMISSED


def test_archive_skips_unknown_ids(tmp_path: Path) -> None:
    """Unknown card ids are skipped, not errors; the count reflects real archives."""
    engine = make_engine(tmp_path)
    c1 = add_card(engine, "rss", "a")
    assert archive_cards(engine, [c1, 9999]) == 1


def test_unarchive_restores_dismissed_to_new(tmp_path: Path) -> None:
    """Unarchive returns a dismissed card to NEW so it reappears in the default list."""
    engine = make_engine(tmp_path)
    c1 = add_card(engine, "rss", "a")
    archive_cards(engine, [c1])
    assert unarchive_cards(engine, [c1]) == 1
    with Session(engine) as s:
        assert s.get(Card, c1).state == CardState.NEW


def test_unarchive_ignores_non_archived_cards(tmp_path: Path) -> None:
    """Only dismissed cards are restored; a NEW card is left untouched (count 0)."""
    engine = make_engine(tmp_path)
    c1 = add_card(engine, "rss", "a")
    assert unarchive_cards(engine, [c1]) == 0


def test_cascade_removes_only_raindrop_items(tmp_path: Path) -> None:
    """The cascade moves Raindrop bookmarks to Processed but skips RSS items (no bookmark)."""
    engine = make_engine(tmp_path)
    rd = add_card(engine, "raindrop", "555")
    rss = add_card(engine, "rss", "a")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            # Respond to GET /rest/v1/collections
            return httpx.Response(200, json={"items": [{"_id": 42, "title": "Processed"}]})
        # Respond to PUT /rest/v1/raindrop/555
        return httpx.Response(200, json={"item": {"_id": 555}})

    result = cascade_raindrop_removal(
        engine, make_settings(tmp_path), [rd, rss], client=mock_client(handler)
    )
    assert result["removed"] == 1
    assert result["skipped_non_raindrop"] == 1
    assert result["errors"] == []
    assert any("PUT" in s and "/raindrop/555" in s for s in seen)


def test_cascade_reports_api_errors_without_raising(tmp_path: Path) -> None:
    """A per-item Raindrop MOVE failure is captured, never raised -- batch survives."""
    engine = make_engine(tmp_path)
    rd = add_card(engine, "raindrop", "555")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            # Collection lookup succeeds so the per-item PUT path is exercised.
            return httpx.Response(200, json={"items": [{"_id": 99, "title": "Processed"}]})
        # Per-item move (PUT /raindrop/555) fails with 403.
        return httpx.Response(403, json={"result": False})

    result = cascade_raindrop_removal(
        engine, make_settings(tmp_path), [rd], client=mock_client(handler)
    )
    assert result["removed"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["card_id"] == rd


def test_cascade_without_a_token_reports_an_error(tmp_path: Path) -> None:
    """No Raindrop token configured -> the cascade reports it instead of calling out."""
    engine = make_engine(tmp_path)
    rd = add_card(engine, "raindrop", "555")
    result = cascade_raindrop_removal(engine, make_settings(tmp_path, token=None), [rd])
    assert result["removed"] == 0
    assert "token" in result["error"].lower()


def test_add_tombstone_is_idempotent(tmp_path: Path) -> None:
    """Calling add_tombstone twice for the same (source, external_id) is a no-op; exactly one row remains."""
    engine = make_engine(tmp_path)
    add_tombstone(engine, "rss", "abc")
    add_tombstone(engine, "rss", "abc")  # must not raise
    with Session(engine) as session:
        rows = session.exec(select(Tombstone).where(Tombstone.source == "rss", Tombstone.external_id == "abc")).all()
    assert len(rows) == 1


def test_delete_cards_removes_all_local_rows_and_tombstones(tmp_path: Path) -> None:
    """delete_cards hard-removes Card, Item, Content, Highlight rows and writes a Tombstone."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "rss", "ext1")

    with Session(engine) as session:
        card = session.get(Card, card_id)
        item_id = card.item_id
        item = session.get(Item, item_id)
        source, external_id = item.source, item.external_id

    store_fulltext(engine, item_id=item_id, markdown="some body text", source_url="u", content_type="text/html", status="ok")
    add_highlight(engine, card_id, quote="some body", start_offset=0, end_offset=9)

    result = delete_cards(engine, make_settings(tmp_path), [card_id])

    assert result == {"deleted": 1, "raindrop": {}}
    with Session(engine) as session:
        assert session.get(Card, card_id) is None
        assert session.exec(select(Item).where(Item.id == item_id)).first() is None
        assert session.exec(select(Content).where(Content.item_id == item_id)).first() is None
        assert session.exec(select(Highlight).where(Highlight.card_id == card_id)).all() == []
        tombstone = session.exec(
            select(Tombstone).where(Tombstone.source == source, Tombstone.external_id == external_id)
        ).first()
        assert tombstone is not None
        # FTS virtual table must be cleaned up alongside the content row.
        remaining = session.connection().execute(
            text("SELECT count(*) FROM content_fts WHERE item_id = :iid"), {"iid": item_id}
        ).scalar()
        assert remaining == 0


def test_deleting_an_item_removes_the_file_you_sent_in_with_it(tmp_path: Path) -> None:
    """A stored picture or PDF leaves the durable store only when its item is deleted."""
    from spyglass_service.radar import from_you_store

    engine = make_engine(tmp_path)
    settings = make_settings(tmp_path)
    mine, other = add_card(engine, "rss", "mine"), add_card(engine, "rss", "other")
    with Session(engine) as session:
        mine_item, other_item = session.get(Card, mine).item_id, session.get(Card, other).item_id
    from_you_store.put(settings.data_dir, mine_item, b"%PDF-1.4 mine")
    from_you_store.put(settings.data_dir, other_item, b"%PDF-1.4 other")

    delete_cards(engine, settings, [mine])

    assert from_you_store.find(settings.data_dir, mine_item) is None
    assert from_you_store.find(settings.data_dir, other_item) is not None
    engine.dispose()


def test_delete_cards_skips_unknown_ids(tmp_path: Path) -> None:
    """delete_cards silently skips card ids that do not exist; count reflects real deletes."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "rss", "ext2")
    result = delete_cards(engine, make_settings(tmp_path), [card_id, 9999])
    assert result["deleted"] == 1


def test_delete_cards_moves_raindrop_to_processed(tmp_path: Path) -> None:
    """delete_cards hard-deletes a raindrop card locally AND moves its bookmark to Processed."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "raindrop", "ext99")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"_id": 42, "title": "Processed"}]})
        return httpx.Response(200, json={"item": {"_id": 99}})

    result = delete_cards(
        engine, make_settings(tmp_path), [card_id], client=mock_client(handler)
    )
    assert result["deleted"] == 1
    assert result["raindrop"]["moved"] == 1
    assert result["raindrop"]["errors"] == []
    with Session(engine) as session:
        assert session.get(Card, card_id) is None
    assert any("PUT" in s and "/raindrop/ext99" in s for s in seen)


def test_delete_cards_rss_only_skips_raindrop(tmp_path: Path) -> None:
    """Deleting an RSS card makes no Raindrop HTTP call and result['raindrop'] is empty dict."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "rss", "rss42")
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    result = delete_cards(
        engine, make_settings(tmp_path), [card_id], client=mock_client(handler)
    )
    assert result["deleted"] == 1
    assert result["raindrop"] == {}
    assert calls == []


def test_delete_cards_without_token_reports_raindrop_error(tmp_path: Path) -> None:
    """Raindrop card with no token: local delete succeeds, raindrop key carries the error, no HTTP call."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "raindrop", "ext77")
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    result = delete_cards(
        engine, make_settings(tmp_path, token=None), [card_id], client=mock_client(handler)
    )
    assert result["deleted"] == 1
    assert "error" in result["raindrop"]
    assert "token" in result["raindrop"]["error"].lower()
    assert calls == []
    with Session(engine) as session:
        assert session.get(Card, card_id) is None


def test_deleted_rss_item_does_not_resurrect(tmp_path: Path) -> None:
    """Integration: after delete, re-collecting the same (source, external_id) must not re-add it."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, "rss", "feed42")

    delete_cards(engine, make_settings(tmp_path), [card_id])

    # Simulate re-collection of the same item from the feed
    store_items(engine, [CollectedItem(source="rss", external_id="feed42", title="T feed42", url="https://x.test")])
    materialize_cards(engine)

    with Session(engine) as session:
        assert session.exec(select(Item).where(Item.source == "rss", Item.external_id == "feed42")).first() is None
        assert session.exec(select(Card)).all() == []


def test_delete_removes_from_in_memory_index(tmp_path: Path) -> None:
    """delete_cards must also evict the deleted item's vector from the live EmbeddingIndex.

    Verifies that after deletion the item_id is absent from the index AND the Embedding
    row is gone from the DB. Callers that pass no index (default None) remain unaffected.
    """
    import numpy as np

    from spyglass_service.embeddings import EmbeddingIndex, embed_pending

    engine = make_engine(tmp_path)
    card_id = add_card(engine, "rss", "idx1")
    with Session(engine) as s:
        item_id = s.get(Card, card_id).item_id

    idx = EmbeddingIndex(lambda ts: np.ones((len(ts), 3), dtype=np.float32), "fake", 3)
    embed_pending(engine, idx)

    assert idx.has(item_id) is True

    delete_cards(engine, make_settings(tmp_path), [card_id], index=idx)

    assert idx.has(item_id) is False
    with Session(engine) as s:
        from spyglass_service.models import Embedding
        assert s.exec(select(Embedding).where(Embedding.item_id == item_id)).first() is None


def test_delete_removes_embedding_row(tmp_path: Path) -> None:
    """delete_cards must also remove the Embedding row for the deleted item."""
    import numpy as np
    from sqlmodel import Session, select

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.embeddings import EmbeddingIndex, embed_pending
    from spyglass_service.lifecycle import delete_cards
    from spyglass_service.models import Card, Embedding, Item

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    with Session(engine) as s:
        item = Item(source="rss", external_id="a", title="T", url="https://x.test", summary="s")
        s.add(item)
        s.commit()
        s.refresh(item)
        s.add(Card(item_id=item.id, summary="s"))
        s.commit()
        card_id = s.exec(select(Card)).first().id
    embed_pending(engine, EmbeddingIndex(lambda ts: np.ones((len(ts), 3), dtype=np.float32), "fake", 3))
    delete_cards(engine, make_settings(tmp_path), [card_id])
    with Session(engine) as s:
        assert s.exec(select(Embedding)).all() == []
