"""Category review tail: list the uncategorized review queue and confirm a category.

The centroid auto-categorizer is retired -- the LLM enrichment pass
assigns categories; `fits=false`/low-confidence items are simply left uncategorized and show
up here for human assignment. Confirmation is unchanged.
"""

from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.categories import _ensure_category
from spyglass_service.models import Card, CardState, Item


def needs_review(engine: Engine) -> list[dict]:
    """Uncategorized, non-dismissed cards awaiting a human category (the LLM 'doesn't fit' tail)."""
    with Session(engine) as session:
        rows = session.exec(
            select(Card.id, Card.item_id, Item.title)
            .where(Card.item_id == Item.id)
            .where(Card.category.is_(None))  # type: ignore[union-attr]
            .where(Card.state != CardState.DISMISSED)
        ).all()
    return [{"card_id": cid, "item_id": iid, "title": title} for cid, iid, title in rows]


def confirm_category(engine: Engine, card_id: int, category: str | None = None) -> dict | None:
    """Confirm (or set) a card's category; override only on a net change. None if unknown card."""
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            return None
        if category is not None and category != card.category:
            _ensure_category(session, category)
            card.category = category
            card.category_override = category != card.category_ai
        card.category_confirmed = True
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
        return {
            "category": card.category,
            "category_confirmed": card.category_confirmed,
            "category_override": card.category_override,
        }
