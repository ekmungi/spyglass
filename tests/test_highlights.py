"""Tests for the highlight store: anchored quotes per card + MCP tool."""

import json
from pathlib import Path

import pytest
from fastmcp import Client
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.highlights import (
    add_highlight,
    delete_for_card,
    delete_highlight,
    list_highlights,
)
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.models import Card, Item


@pytest.fixture
def state(tmp_path: Path) -> ServiceState:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    return ServiceState(settings=settings, engine=engine)


def seed_card(state: ServiceState) -> int:
    with Session(state.engine) as session:
        item = Item(source="rss", external_id="a", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def test_add_and_list_highlights_with_anchor(state: ServiceState) -> None:
    """A highlight stores its quote plus char offsets into the stored markdown."""
    card_id = seed_card(state)
    created = add_highlight(
        state.engine, card_id, quote="memory eviction policy", start_offset=120, end_offset=143
    )
    assert created["id"] > 0
    rows = list_highlights(state.engine, card_id)
    assert len(rows) == 1
    assert rows[0]["quote"] == "memory eviction policy"
    assert rows[0]["start_offset"] == 120
    assert rows[0]["end_offset"] == 143
    assert rows[0]["card_id"] == card_id


def test_add_highlight_unknown_card_returns_none(state: ServiceState) -> None:
    assert add_highlight(state.engine, 9999, quote="q", start_offset=0, end_offset=1) is None


def test_offsets_are_optional_quote_is_the_fallback_anchor(state: ServiceState) -> None:
    """Offsets may be unknown; the quote alone still anchors via text search."""
    card_id = seed_card(state)
    created = add_highlight(state.engine, card_id, quote="just a quote")
    assert created["start_offset"] is None
    assert created["end_offset"] is None


def test_delete_for_card_removes_all(state: ServiceState) -> None:
    """delete_for_card removes every highlight for that card and returns the count."""
    card_id = seed_card(state)
    add_highlight(state.engine, card_id, quote="first quote", start_offset=0, end_offset=5)
    add_highlight(state.engine, card_id, quote="second quote", start_offset=10, end_offset=22)
    count = delete_for_card(state.engine, card_id)
    assert count == 2
    assert list_highlights(state.engine, card_id) == []


def test_delete_for_card_empty_card_returns_zero(state: ServiceState) -> None:
    """delete_for_card on a card with no highlights returns 0, not an error."""
    card_id = seed_card(state)
    assert delete_for_card(state.engine, card_id) == 0


def test_delete_highlight(state: ServiceState) -> None:
    card_id = seed_card(state)
    created = add_highlight(state.engine, card_id, quote="q", start_offset=0, end_offset=1)
    assert delete_highlight(state.engine, created["id"]) is True
    assert list_highlights(state.engine, card_id) == []
    assert delete_highlight(state.engine, created["id"]) is False


async def test_mcp_get_highlights_returns_card_highlights(state: ServiceState) -> None:
    """Send to Claude routes highlights through the get_highlights MCP tool."""
    card_id = seed_card(state)
    add_highlight(state.engine, card_id, quote="key passage", start_offset=5, end_offset=16)
    async with Client(build_mcp(state)) as client:
        result = await client.call_tool("get_highlights", {"card_id": card_id})
    payload = json.loads(result.content[0].text)
    assert payload["highlights"][0]["quote"] == "key passage"


async def test_mcp_get_highlights_unknown_card(state: ServiceState) -> None:
    async with Client(build_mcp(state)) as client:
        result = await client.call_tool("get_highlights", {"card_id": 9999})
    payload = json.loads(result.content[0].text)
    assert "error" in payload
