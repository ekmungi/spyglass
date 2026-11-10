"""Tests for the article-feedback helper: set/clear + learning-signal list."""

from pathlib import Path

import pytest
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.feedback import list_feedback, set_feedback
from spyglass_service.models import Card, Item


def _seed(engine) -> int:
    """Insert one item + card and return the card id."""
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


def _engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    return engine


def test_set_feedback_up(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    card_id = _seed(engine)
    result = set_feedback(engine, card_id, "up")
    assert result["feedback"] == "up"
    assert result["feedback_at"] is not None


def test_clear_feedback_nulls_timestamp(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    card_id = _seed(engine)
    set_feedback(engine, card_id, "up")
    result = set_feedback(engine, card_id, None)
    assert result["feedback"] is None
    assert result["feedback_at"] is None


def test_invalid_value_raises(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    card_id = _seed(engine)
    with pytest.raises(ValueError):
        set_feedback(engine, card_id, "sideways")


def test_unknown_card_returns_none(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert set_feedback(engine, 9999, "up") is None


def test_list_feedback_returns_only_thumbed(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    card_id = _seed(engine)
    set_feedback(engine, card_id, "down")
    rows = list_feedback(engine)
    assert len(rows) == 1
    assert rows[0]["card_id"] == card_id
    assert rows[0]["feedback"] == "down"
    assert rows[0]["title"] == "T"


def test_cleared_feedback_drops_out_of_list(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    card_id = _seed(engine)
    set_feedback(engine, card_id, "up")
    set_feedback(engine, card_id, None)
    assert list_feedback(engine) == []


# ---------------------------------------------------------------------------
# Thumb -> relevance pin: down = decisive OUT pin,
# up = soft boost (no level pin), leaving 'down' releases the pin.
# ---------------------------------------------------------------------------


def _seed_with_ai(engine, ai: str = "medium") -> int:
    """Insert one item + card whose AI relevance baseline is `ai`; return the card id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id="p", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s", relevance=ai, relevance_ai=ai)
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def _card(engine, card_id: int) -> Card:
    with Session(engine) as session:
        return session.get(Card, card_id)


def test_thumb_down_pins_relevance_out_with_override(tmp_path: Path) -> None:
    """Thumb-down is a decisive OUT: it pins relevance='out' and flags the override."""
    engine = _engine(tmp_path)
    card_id = _seed_with_ai(engine, ai="high")
    set_feedback(engine, card_id, "down")
    card = _card(engine, card_id)
    assert card.relevance == "out"
    assert card.relevance_override is True


def test_thumb_up_does_not_pin_a_relevance_level(tmp_path: Path) -> None:
    """Thumb-up is a soft boost, not a level-setter: relevance/override are untouched."""
    engine = _engine(tmp_path)
    card_id = _seed_with_ai(engine, ai="medium")
    set_feedback(engine, card_id, "up")
    card = _card(engine, card_id)
    assert card.relevance == "medium"
    assert card.relevance_override is False


def test_clearing_a_down_releases_the_out_pin(tmp_path: Path) -> None:
    """Clearing a thumb-down reverts the card to its AI baseline and drops the override."""
    engine = _engine(tmp_path)
    card_id = _seed_with_ai(engine, ai="high")
    set_feedback(engine, card_id, "down")
    set_feedback(engine, card_id, None)
    card = _card(engine, card_id)
    assert card.relevance == "high"
    assert card.relevance_override is False


def test_switching_down_to_up_releases_the_out_pin(tmp_path: Path) -> None:
    """Thumbing up after a thumb-down releases the OUT pin (up is not a level-setter)."""
    engine = _engine(tmp_path)
    card_id = _seed_with_ai(engine, ai="high")
    set_feedback(engine, card_id, "down")
    set_feedback(engine, card_id, "up")
    card = _card(engine, card_id)
    assert card.feedback == "up"
    assert card.relevance == "high"
    assert card.relevance_override is False
