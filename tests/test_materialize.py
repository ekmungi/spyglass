"""Tests for materializing a card per collected item (so the dashboard is interactive)."""

from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.cards import materialize_cards
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, CardState, Item


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def add_item(engine, ext_id: str, summary: str | None = "raw") -> int:
    with Session(engine) as session:
        item = Item(source="raindrop", external_id=ext_id, title=f"T {ext_id}",
                    url="https://x.test", summary=summary)
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


def test_creates_an_uncurated_card_per_cardless_item(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "a")
    add_item(engine, "b")
    created = materialize_cards(engine)
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
    assert created == 2
    assert all(c.curated is False and c.state == CardState.NEW for c in cards)


def test_uses_item_summary_then_falls_back_to_title(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "withsum", summary="an excerpt")
    add_item(engine, "nosum", summary=None)
    materialize_cards(engine)
    with Session(engine) as session:
        cards = {c.item_id: c for c in session.exec(select(Card)).all()}
        items = {i.id: i for i in session.exec(select(Item)).all()}
    by_ext = {items[c.item_id].external_id: c for c in cards.values()}
    assert by_ext["withsum"].summary == "an excerpt"
    assert by_ext["nosum"].summary == "T nosum"


def test_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "a")
    materialize_cards(engine)
    created = materialize_cards(engine)
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
    assert created == 0
    assert len(cards) == 1
