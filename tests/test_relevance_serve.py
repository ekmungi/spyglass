"""Tests for the relevance-serve adapter: gather thumb labels + embedding
vectors and compute each card's blended effective relevance via the pure model core."""

from pathlib import Path

import numpy as np
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.feedback import set_feedback
from spyglass_service.models import Card, Item
from spyglass_service.relevance import set_user_relevance
from spyglass_service.relevance_serve import effective_relevance_map


def _engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "serve.db")
    init_db(engine)
    return engine


def _index_with(vectors: dict[int, list[float]], dim: int) -> EmbeddingIndex:
    """Build an EmbeddingIndex holding the given normalized vectors, keyed by item_id."""
    idx = EmbeddingIndex(
        embed_fn=lambda t: np.zeros((len(t), dim), dtype=np.float32), model="test", dim=dim
    )
    for iid, raw in vectors.items():
        arr = np.array(raw, dtype=np.float32)
        arr = arr / float(np.linalg.norm(arr))
        idx.add(iid, arr.tobytes())
    return idx


def _add_card(engine, ext: str, **card_fields) -> tuple[int, int]:
    """Insert one item + card with the given Card fields; return (item_id, card_id)."""
    with Session(engine) as session:
        item = Item(source="rss", external_id=ext, title=f"T{ext}", url=f"https://x.test/{ext}")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s", **card_fields)
        session.add(card)
        session.commit()
        session.refresh(card)
        return item.id, card.id


def _rows(engine):
    """Return [(Card, Item)] like list_cards passes to the adapter."""
    from sqlmodel import select

    with Session(engine) as session:
        return [
            (session.get(Card, c.id), session.get(Item, c.item_id))
            for c in session.exec(select(Card)).all()
        ]


def test_no_thumbs_judged_card_maps_to_its_prior_bucket(tmp_path: Path) -> None:
    """With no thumbs, a judged card's effective relevance is just its prior bucket."""
    from datetime import UTC, datetime

    engine = _engine(tmp_path)
    _item, card_id = _add_card(
        engine, "a", relevance_score=55, relevance="medium", relevance_ai="medium",
        relevance_at=datetime.now(UTC),
    )
    idx = _index_with({}, dim=2)
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card_id] == "medium"


def test_unjudged_card_is_none(tmp_path: Path) -> None:
    """A card never scored and never thumbed resolves to None (unjudged)."""
    engine = _engine(tmp_path)
    _item, card_id = _add_card(engine, "u")  # no relevance, no relevance_at, no feedback
    idx = _index_with({}, dim=2)
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card_id] is None


def test_thumb_up_lifts_a_near_neighbour(tmp_path: Path) -> None:
    """A thumb-up on a semantically-close article lifts the neighbour's effective relevance."""
    from datetime import UTC, datetime

    engine = _engine(tmp_path)
    item1, card1 = _add_card(engine, "1")  # will be thumbed up
    item2, card2 = _add_card(
        engine, "2", relevance_score=55, relevance="medium", relevance_ai="medium",
        relevance_at=datetime.now(UTC),
    )
    idx = _index_with({item1: [1.0, 0.0], item2: [0.98, 0.2]}, dim=2)  # cosine ~0.98
    set_feedback(engine, card1, "up")
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card2] == "high"  # lifted from medium by the close positive label


def test_thumb_down_sinks_a_near_neighbour_and_pins_itself_out(tmp_path: Path) -> None:
    """A thumb-down sinks a close neighbour and, via the OUT pin, shows itself as out."""
    from datetime import UTC, datetime

    engine = _engine(tmp_path)
    item3, card3 = _add_card(engine, "3", relevance="medium", relevance_ai="medium")
    item4, card4 = _add_card(
        engine, "4", relevance_score=55, relevance="medium", relevance_ai="medium",
        relevance_at=datetime.now(UTC),
    )
    idx = _index_with({item3: [1.0, 0.0], item4: [0.98, 0.2]}, dim=2)
    set_feedback(engine, card3, "down")  # decisive OUT + negative label
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card3] == "out"          # own OUT pin (override wins)
    assert eff[card4] == "low"          # sunk from medium by the close negative label


def test_duplicate_item_labels_dedupe_to_most_recent(tmp_path: Path) -> None:
    """If two cards reference the same item, the label pool keeps only the most recent thumb."""
    from datetime import UTC, datetime, timedelta

    from spyglass_service.relevance_serve import build_label_pool

    engine = _engine(tmp_path)
    now = datetime.now(UTC)
    with Session(engine) as session:
        item = Item(source="rss", external_id="dup", title="T", url="https://x.test/dup")
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
        # Older thumb-down and a newer thumb-up on the SAME item (two cards).
        session.add(Card(item_id=item_id, summary="s", feedback="down",
                         feedback_at=now - timedelta(days=1)))
        session.add(Card(item_id=item_id, summary="s", feedback="up", feedback_at=now))
        session.commit()
    pool = build_label_pool(engine)
    for_item = [label for label in pool if label.item_id == item_id]
    assert len(for_item) == 1
    assert for_item[0].polarity == 1.0  # the most recent (up) wins, not double-counted


def test_thumb_down_then_clear_on_unscored_card_returns_to_unjudged(tmp_path: Path) -> None:
    """Clearing a thumb-down on a never-AI-scored card returns it to unjudged (effective None)."""
    engine = _engine(tmp_path)
    _item, card_id = _add_card(engine, "x")  # no relevance / relevance_ai / relevance_at
    set_feedback(engine, card_id, "down")
    set_feedback(engine, card_id, None)  # clear releases the pin
    idx = _index_with({}, dim=2)
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card_id] is None


def test_manual_override_wins_over_propagation(tmp_path: Path) -> None:
    """An explicit user override holds even when a close thumb-down would otherwise sink it."""
    engine = _engine(tmp_path)
    item5, card5 = _add_card(engine, "5")  # thumbed down (negative label)
    item6, card6 = _add_card(
        engine, "6", relevance="medium", relevance_ai="medium",
    )
    idx = _index_with({item5: [1.0, 0.0], item6: [0.98, 0.2]}, dim=2)
    set_feedback(engine, card5, "down")
    set_user_relevance(engine, card6, "high")  # explicit override
    eff = effective_relevance_map(engine, idx, _rows(engine))
    assert eff[card6] == "high"
