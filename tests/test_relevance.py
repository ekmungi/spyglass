"""Tests for relevance assignment + net-change user override.

The learning signal is the override STATE (current value != the AI's value), so a
revert to the AI value clears it automatically -- no append-only log to prune.
"""

from pathlib import Path

from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, Item
from spyglass_service.relevance import (
    RelevanceResult,
    apply_relevance,
    list_overrides,
    set_user_relevance,
)


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def add_card(engine) -> int:
    """Insert an item + card; return the card id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id="a", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def get_card(engine, card_id: int) -> Card:
    with Session(engine) as session:
        return session.get(Card, card_id)


def test_apply_relevance_sets_value_and_ai_baseline(tmp_path: Path) -> None:
    """The AI pass sets the value, records it as the AI baseline, no override."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    n = apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="high", reason="agentic AI")])
    card = get_card(engine, card_id)
    assert n == 1
    assert card.relevance == "high"
    assert card.relevance_ai == "high"
    assert card.relevance_reason == "agentic AI"
    assert card.relevance_override is False


def test_apply_relevance_skips_user_overridden_cards(tmp_path: Path) -> None:
    """A re-run of the AI pass must not re-clobber a value the user set."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="high", reason="ai")])
    set_user_relevance(engine, card_id, "low")
    applied = apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="medium", reason="ai again")])
    card = get_card(engine, card_id)
    assert applied == 0  # skipped
    assert card.relevance == "low"
    assert card.relevance_override is True


def test_set_user_relevance_flags_override_on_net_change(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="high", reason="ai")])
    result = set_user_relevance(engine, card_id, "low")
    card = get_card(engine, card_id)
    assert result["relevance_override"] is True
    assert card.relevance == "low"
    assert card.relevance_override is True


def test_set_user_relevance_revert_clears_override(tmp_path: Path) -> None:
    """Toggling back to the AI's value voids the signal (override clears)."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="high", reason="ai")])
    set_user_relevance(engine, card_id, "low")
    set_user_relevance(engine, card_id, "high")  # revert to AI value
    card = get_card(engine, card_id)
    assert card.relevance == "high"
    assert card.relevance_override is False


def test_set_user_relevance_unknown_card_returns_none(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    assert set_user_relevance(engine, 999, "high") is None


def test_set_user_relevance_clear_reverts_to_ai_and_drops_override(tmp_path: Path) -> None:
    """Passing None reverts the card to its AI baseline and clears the override."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="medium", reason="ai")])
    set_user_relevance(engine, card_id, "out")  # user override
    result = set_user_relevance(engine, card_id, None)  # clear it
    card = get_card(engine, card_id)
    assert result["relevance"] == "medium"
    assert result["relevance_override"] is False
    assert card.relevance == "medium"
    assert card.relevance_override is False


def test_list_overrides_returns_user_changed_cards(tmp_path: Path) -> None:
    """The learning signal: cards whose value differs from the AI's."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_relevance(engine, [RelevanceResult(card_id=card_id, relevance="high", reason="ai")])
    set_user_relevance(engine, card_id, "low")
    overrides = list_overrides(engine)
    assert len(overrides) == 1
    assert overrides[0]["card_id"] == card_id
    assert overrides[0]["relevance"] == "low"
    assert overrides[0]["relevance_ai"] == "high"
