"""Relevance assignment + net-change user override.

The learning signal is the override state (current value != the AI's value), so a
user's revert to the AI value clears it automatically -- there is no append-only
log to prune, and preferences.md never learns a net-zero nudge.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Item


@dataclass(frozen=True)
class RelevanceResult:
    """One relevance judgment from the AI pass (high / medium / low / out)."""

    card_id: int
    relevance: str
    reason: str | None = None


def apply_relevance(engine: Engine, results: list[RelevanceResult]) -> int:
    """Apply AI relevance judgments to cards.

    Sets the value, records it as the AI baseline, and stores the reason. Never
    re-clobbers a card the user has overridden. Returns how many were applied.
    """
    applied = 0
    with Session(engine) as session:
        for result in results:
            card = session.get(Card, result.card_id)
            if card is None or card.relevance_override:
                continue
            card.relevance = result.relevance
            card.relevance_ai = result.relevance
            card.relevance_reason = result.reason
            card.relevance_at = datetime.now(UTC)
            card.relevance_override = False
            card.updated_at = datetime.now(UTC)
            session.add(card)
            applied += 1
        session.commit()
    return applied


def set_user_relevance(engine: Engine, card_id: int, relevance: str | None) -> dict | None:
    """Record (or clear) a user's relevance choice for one card.

    A concrete value sets relevance and flags override when it differs from the AI's
    value (the net-change rule). Passing None clears the manual override, reverting
    the card to its AI baseline (the editable escape hatch). Returns the
    new {relevance, relevance_override}, or None if the card is unknown.
    """
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            return None
        if relevance is None:
            # Clear the manual override: fall back to the AI baseline so an unlabeled
            # item's displayed level comes from the blended score again.
            card.relevance = card.relevance_ai
            card.relevance_override = False
        else:
            card.relevance = relevance
            card.relevance_override = relevance != card.relevance_ai
        card.relevance_at = datetime.now(UTC)
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
        return {"relevance": card.relevance, "relevance_override": card.relevance_override}


def list_overrides(engine: Engine) -> list[dict]:
    """Cards the user has overridden -- relevance and/or category differs from the AI's
    value. This is the learning signal for the preferences skill; a revert
    clears the override, so net-zero nudges never appear here.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Card, Item)
            .where(Card.item_id == Item.id)
            .where((Card.relevance_override == True) | (Card.category_override == True))  # noqa: E712
        ).all()
    return [
        {
            "card_id": card.id,
            "title": item.title,
            "relevance": card.relevance,
            "relevance_ai": card.relevance_ai,
            "category": card.category,
            "category_ai": card.category_ai,
        }
        for card, item in rows
    ]
