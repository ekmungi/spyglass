"""Tests for the MCP server tools (in-memory fastmcp client, no network)."""

import json
from pathlib import Path

import pytest
from fastmcp import Client
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.models import Card, CardState, Item, Tombstone


@pytest.fixture
def state(tmp_path: Path) -> ServiceState:
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        vault_path=vault,
        interest_note_path=vault / "interests.md",
    )
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    return ServiceState(settings=settings, engine=engine)


def add_item(state: ServiceState, ext_id: str) -> int:
    with Session(state.engine) as session:
        item = Item(source="rss", external_id=ext_id, title=f"T {ext_id}", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


async def call(state: ServiceState, tool: str, **kwargs):
    """Invoke one MCP tool in-memory and return its parsed payload."""
    async with Client(build_mcp(state)) as client:
        result = await client.call_tool(tool, kwargs)
    return json.loads(result.content[0].text)


async def test_get_pending_items_lists_uncarded_items(state: ServiceState) -> None:
    item_id = add_item(state, "a")
    payload = await call(state, "get_pending_items")
    assert payload["items"][0]["id"] == item_id


async def test_save_cards_enriches_and_reports_count(state: ServiceState) -> None:
    item_id = add_item(state, "a")
    payload = await call(
        state, "save_cards", cards=[{"item_id": item_id, "summary": "s", "tags": ["x"]}]
    )
    assert payload["enriched"] == 1
    with Session(state.engine) as session:
        cards = session.exec(select(Card)).all()
    assert len(cards) == 1
    assert cards[0].curated is True


async def test_get_groups_lists_existing_groups(state: ServiceState) -> None:
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    from spyglass_service.curation import assign_groups
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card = session.exec(select(Card)).first()
    assign_groups(state.engine, {card.item_id: "Agentic AI"})
    payload = await call(state, "get_groups")
    assert payload["groups"] == [{"group": "Agentic AI", "count": 1}]


async def test_organize_labels_pending_items_into_groups(state: ServiceState) -> None:
    item_id = add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    payload = await call(
        state, "organize", groups=[{"item_id": item_id, "group": "Agentic AI"}]
    )
    assert payload["labelled"] == 1
    with Session(state.engine) as session:
        card = session.exec(select(Card)).first()
    assert card.group_label == "Agentic AI"


async def test_set_relevance_assigns_scores_and_baseline(state: ServiceState) -> None:
    """The relevance pass records each card's score + reason via set_relevance."""
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    payload = await call(
        state, "set_relevance",
        items=[{"card_id": card_id, "relevance": "high", "reason": "matches agentic AI"}],
    )
    assert payload["assessed"] == 1
    with Session(state.engine) as session:
        card = session.get(Card, card_id)
    assert card.relevance == "high"
    assert card.relevance_ai == "high"
    assert card.relevance_reason == "matches agentic AI"


async def test_get_interest_profile_returns_note_text(state: ServiceState) -> None:
    state.settings.interest_note_path.write_text("agentic AI only", encoding="utf-8")
    payload = await call(state, "get_interest_profile")
    assert "agentic AI" in payload["profile"]


async def test_selection_roundtrip(state: ServiceState) -> None:
    """The dashboard marks a selection; a Claude session reads it back."""
    state.set_selection([3, 5])
    payload = await call(state, "get_selection")
    assert payload["card_ids"] == [3, 5]


async def test_fetch_document_downloads_and_returns_text(state: ServiceState, monkeypatch) -> None:
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id

    def fake_fetch(url, dest, **kwargs):
        return {"path": str(dest / "p.pdf"), "content_type": "application/pdf", "text": "PAPER"}

    monkeypatch.setattr("spyglass_service.documents.fetch_document", fake_fetch)
    payload = await call(state, "fetch_document", card_id=card_id)
    assert payload["text"] == "PAPER"
    assert payload["path"].endswith("p.pdf")


async def test_store_fulltext_fetches_and_stores_markdown(state: ServiceState, monkeypatch) -> None:
    """The relevance skill calls store_fulltext to populate a keeper's full text."""
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id

    def stub(url: str) -> dict:
        return {"markdown": "# Body", "content_type": "text/html", "status": "ok",
                "error": None, "source_url": url}

    monkeypatch.setattr("spyglass_service.fulltext.fetch_fulltext", stub)
    payload = await call(state, "store_fulltext", card_id=card_id)
    assert payload["status"] == "ok"
    assert payload["text_chars"] == len("# Body")


async def test_get_fulltext_returns_stored_markdown(state: ServiceState) -> None:
    item_id = add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    from spyglass_service.content_store import store_fulltext
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    store_fulltext(state.engine, item_id=item_id, markdown="# Body", source_url="u", content_type="text/html", status="ok")
    payload = await call(state, "get_fulltext", card_id=card_id)
    assert payload["status"] == "ok"
    assert payload["markdown"] == "# Body"


async def test_get_fulltext_absent_reports_status(state: ServiceState) -> None:
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    payload = await call(state, "get_fulltext", card_id=card_id)
    assert payload["status"] == "absent"
    assert payload["markdown"] is None


async def test_categorize_assigns_categories(state: ServiceState) -> None:
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    payload = await call(state, "categorize", items=[{"card_id": card_id, "category": "Agentic AI"}])
    assert payload["categorized"] == 1
    with Session(state.engine) as session:
        card = session.get(Card, card_id)
    assert card.category == "Agentic AI"
    assert card.category_ai == "Agentic AI"


async def test_get_categories_lists_with_counts(state: ServiceState) -> None:
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    await call(state, "categorize", items=[{"card_id": card_id, "category": "Agentic AI"}])
    payload = await call(state, "get_categories")
    row = next(c for c in payload["categories"] if c["name"] == "Agentic AI")
    assert row["count"] == 1


async def test_get_pending_items_includes_card_id(state: ServiceState) -> None:
    """The relevance/categorize skill needs each item's card id to act on it."""
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    payload = await call(state, "get_pending_items")
    assert payload["items"][0]["card_id"] == card_id


async def test_get_preferences_returns_note(state: ServiceState) -> None:
    """The relevance + preference skills read the learned-preferences note."""
    state.settings.preferences_note_path = state.settings.vault_path / "preferences.md"
    state.settings.preferences_note_path.write_text("Prefer agentic AI.", encoding="utf-8")
    payload = await call(state, "get_preferences")
    assert "agentic AI" in payload["preferences"]


async def test_get_overrides_lists_user_changes(state: ServiceState) -> None:
    """The preference skill reads the user's override signals to learn from them."""
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    from spyglass_service.relevance import RelevanceResult, apply_relevance, set_user_relevance
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    apply_relevance(state.engine, [RelevanceResult(card_id=card_id, relevance="high", reason="ai")])
    set_user_relevance(state.engine, card_id, "low")
    payload = await call(state, "get_overrides")
    assert payload["overrides"][0]["card_id"] == card_id


async def test_get_feedback_lists_thumbed_cards(state: ServiceState) -> None:
    """The preference skill reads the user's thumbs-up/down as a learning signal."""
    add_item(state, "a")
    from spyglass_service.cards import materialize_cards
    from spyglass_service.feedback import set_feedback
    materialize_cards(state.engine)
    with Session(state.engine) as session:
        card_id = session.exec(select(Card)).first().id
    set_feedback(state.engine, card_id, "up")
    payload = await call(state, "get_feedback")
    assert payload["feedback"][0]["card_id"] == card_id
    assert payload["feedback"][0]["feedback"] == "up"


async def test_save_briefing_writes_note_and_finishes_the_card(state: ServiceState) -> None:
    item_id = add_item(state, "a")
    with Session(state.engine) as session:
        card = Card(item_id=item_id, summary="s", state=CardState.QUEUED)
        session.add(card)
        session.commit()
        session.refresh(card)
        card_id = card.id
    payload = await call(
        state, "save_briefing", card_id=card_id, title="Sync engines", markdown="# B"
    )
    briefing = Path(payload["path"])
    assert briefing.is_file()
    with Session(state.engine) as session:
        refreshed = session.get(Card, card_id)
    assert refreshed.state == CardState.FINISHED
    assert refreshed.briefing_path == str(briefing)


def _materialize_card_id(state: ServiceState, item_id: int) -> int:
    """Materialize the raw card for an item and return its card_id."""
    from spyglass_service.cards import materialize_cards

    materialize_cards(state.engine)
    with Session(state.engine) as session:
        return session.exec(select(Card).where(Card.item_id == item_id)).one().id


async def test_archive_items_dismisses_cards(state: ServiceState) -> None:
    """archive_items soft-archives a processed card (state DISMISSED), not deleted."""
    card_id = _materialize_card_id(state, add_item(state, "a"))
    payload = await call(state, "archive_items", card_ids=[card_id])
    assert payload["archived"] == 1
    with Session(state.engine) as session:
        assert session.get(Card, card_id).state == CardState.DISMISSED


async def test_unarchive_items_restores_cards(state: ServiceState) -> None:
    """unarchive_items returns an archived card to NEW so it reappears."""
    card_id = _materialize_card_id(state, add_item(state, "a"))
    await call(state, "archive_items", card_ids=[card_id])
    payload = await call(state, "unarchive_items", card_ids=[card_id])
    assert payload["unarchived"] == 1
    with Session(state.engine) as session:
        assert session.get(Card, card_id).state == CardState.NEW


async def test_archive_items_raindrop_cascade_reports_missing_token(state: ServiceState) -> None:
    """remove_from_raindrop with no token configured archives anyway and reports the
    cascade error -- no network call, no move to Processed (the fixture has no raindrop_token)."""
    card_id = _materialize_card_id(state, add_item(state, "a"))
    payload = await call(
        state, "archive_items", card_ids=[card_id], remove_from_raindrop=True
    )
    assert payload["archived"] == 1
    assert payload["raindrop_removed"] == 0
    assert "raindrop_error" in payload


async def test_delete_items_removes_card(state: ServiceState) -> None:
    """delete_items hard-deletes the card and leaves a tombstone to block re-collection."""
    card_id = _materialize_card_id(state, add_item(state, "del-1"))
    payload = await call(state, "delete_items", card_ids=[card_id])
    assert payload["deleted"] == 1
    with Session(state.engine) as session:
        assert session.get(Card, card_id) is None
        tombstones = session.exec(select(Tombstone)).all()
    assert len(tombstones) == 1


async def test_delete_items_reports_count_zero_for_unknown(state: ServiceState) -> None:
    """delete_items silently skips unknown card ids and returns deleted=0."""
    payload = await call(state, "delete_items", card_ids=[9999])
    assert payload["deleted"] == 0


async def test_find_similar_returns_neighbours(state: ServiceState) -> None:
    """find_similar returns id/title/score neighbours for a card."""
    from sqlmodel import Session, select

    from spyglass_service.cards import materialize_cards
    from spyglass_service.embeddings import embed_pending
    from spyglass_service.models import Card

    add_item(state, "a")
    add_item(state, "b")
    materialize_cards(state.engine)
    embed_pending(state.engine, state.ensure_index())
    with Session(state.engine) as session:
        cid = session.exec(select(Card)).first().id

    payload = await call(state, "find_similar", card_id=cid)

    assert "similar" in payload
    assert len(payload["similar"]) == 1
    neighbour = payload["similar"][0]
    assert set(neighbour) == {"card_id", "title", "score"}


async def test_store_fulltext_stores_without_deep_embed(state: ServiceState) -> None:
    """store_fulltext persists content but no longer creates a deep embedding."""
    from sqlmodel import Session, select

    from spyglass_service.cards import materialize_cards
    from spyglass_service.models import Card, Embedding

    add_item(state, "a")
    materialize_cards(state.engine)
    with Session(state.engine) as s:
        card_id = s.exec(select(Card)).first().id
    result = await call(state, "store_fulltext", card_id=card_id, markdown="a body about the topic")
    assert result["status"] == "ok"
    with Session(state.engine) as s:
        deep = s.exec(select(Embedding).where(Embedding.text_source == "deep")).first()
    assert deep is None  # deep / mean-pool embedding is retired


async def test_categorize_confirms_value(state: ServiceState) -> None:
    """Categorize via the review tool records the category as confirmed."""
    from spyglass_service.cards import materialize_cards
    from spyglass_service.models import Card

    add_item(state, "a")
    materialize_cards(state.engine)
    with Session(state.engine) as s:
        card_id = s.exec(select(Card)).first().id
    await call(state, "categorize", items=[{"card_id": card_id, "category": "AI"}])
    with Session(state.engine) as s:
        card = s.get(Card, card_id)
    assert card.category == "AI" and card.category_confirmed is True


async def test_get_review_queue_returns_uncategorized(state: ServiceState) -> None:
    """get_review_queue returns a queue of uncategorized, non-dismissed cards."""
    from spyglass_service.cards import materialize_cards
    from spyglass_service.models import Card

    add_item(state, "sc")
    materialize_cards(state.engine)
    with Session(state.engine) as s:
        card_id = s.exec(select(Card)).first().id  # uncategorized by default

    payload = await call(state, "get_review_queue")
    assert "spot_check" not in payload
    assert "queue" in payload
    card_ids = [r["card_id"] for r in payload["queue"]]
    assert card_id in card_ids
    entry = payload["queue"][0]
    assert set(entry) == {"card_id", "item_id", "title"}


async def test_confirm_categories_confirms_batch_and_returns_count(state: ServiceState) -> None:
    """confirm_categories confirms a batch without changing values and returns {confirmed: n}."""
    from spyglass_service.cards import materialize_cards
    from spyglass_service.models import Card

    add_item(state, "a")
    materialize_cards(state.engine)
    with Session(state.engine) as s:
        card_id = s.exec(select(Card)).first().id
    # First categorize so the card has a value to confirm.
    await call(state, "categorize", items=[{"card_id": card_id, "category": "AI"}])
    # Reset confirmed flag to simulate an auto-assigned (unconfirmed) card.
    with Session(state.engine) as s:
        card = s.get(Card, card_id)
        card.category_confirmed = False
        s.add(card)
        s.commit()
    # Now confirm via the batch tool.
    payload = await call(state, "confirm_categories", card_ids=[card_id])
    assert payload["confirmed"] == 1
    with Session(state.engine) as s:
        card = s.get(Card, card_id)
    assert card.category_confirmed is True
    assert card.category == "AI"  # value unchanged


async def test_review_count_tool_reports_count(state: ServiceState) -> None:
    """review_count returns needs_review >= 1 when an uncategorized card exists."""
    from spyglass_service.cards import materialize_cards

    add_item(state, "rc")
    materialize_cards(state.engine)  # one uncategorized card

    payload = await call(state, "review_count")
    assert "needs_review" in payload
    assert payload["needs_review"] >= 1


def add_brief(state: ServiceState, *, markdown: str, ext_ids: list[str], created_at) -> tuple[int, list[int]]:
    """Insert a Brief and one Item+Card per ext_id, all linked via Card.brief_id.

    Returns (brief_id, [card_id, ...]) for the referenced cards.
    """
    from datetime import timedelta

    from spyglass_service.models import Brief

    with Session(state.engine) as session:
        brief = Brief(
            covers_from=created_at - timedelta(days=1),
            covers_until=created_at,
            markdown=markdown,
            item_count=len(ext_ids),
            low_count=0,
            created_at=created_at,
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        card_ids: list[int] = []
        for ext in ext_ids:
            item = Item(source="rss", external_id=ext, title=f"Title {ext}", url=f"https://x/{ext}")
            session.add(item)
            session.commit()
            session.refresh(item)
            card = Card(item_id=item.id, state=CardState.NEW, summary="s", brief_id=brief.id)
            session.add(card)
            session.commit()
            session.refresh(card)
            card_ids.append(card.id)
        return brief.id, card_ids


async def test_get_brief_returns_latest_with_card_references(state: ServiceState) -> None:
    """No id -> newest brief, its markdown, and the articles it references (card_id, title, url)."""
    from datetime import UTC, datetime

    add_brief(state, markdown="old", ext_ids=["a"], created_at=datetime(2026, 7, 1, tzinfo=UTC))
    newer_id, cards = add_brief(
        state, markdown="new brief body", ext_ids=["b", "c"],
        created_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    payload = await call(state, "get_brief")

    assert payload["id"] == newer_id
    assert payload["markdown"] == "new brief body"
    assert {c["card_id"] for c in payload["cards"]} == set(cards)
    assert all(c["title"] and c["url"] for c in payload["cards"])


async def test_get_brief_by_id_returns_that_brief(state: ServiceState) -> None:
    """An explicit brief_id returns that brief even when a newer one exists."""
    from datetime import UTC, datetime

    older_id, _ = add_brief(
        state, markdown="older", ext_ids=["a"], created_at=datetime(2026, 7, 1, tzinfo=UTC)
    )
    add_brief(state, markdown="newer", ext_ids=["b"], created_at=datetime(2026, 7, 2, tzinfo=UTC))

    payload = await call(state, "get_brief", brief_id=older_id)

    assert payload["id"] == older_id
    assert payload["markdown"] == "older"


async def test_get_brief_with_no_briefs_returns_error(state: ServiceState) -> None:
    """No briefs -> an explicit empty answer, never a crash."""
    payload = await call(state, "get_brief")
    assert "error" in payload


async def test_get_brief_unknown_id_returns_error(state: ServiceState) -> None:
    """An unknown brief_id -> an explicit error, not a 500."""
    payload = await call(state, "get_brief", brief_id=999)
    assert "error" in payload


async def test_get_handoff_returns_the_long_prompt(state: ServiceState) -> None:
    """A prompt too long for the claude:// link is fetched by the session."""
    handoff_id = state.handoffs.put("the whole transcript")
    assert await call(state, "get_handoff", handoff_id=handoff_id) == {"text": "the whole transcript"}
    missing = await call(state, "get_handoff", handoff_id="nope")
    assert missing["error"] == "not_found"
