"""Article feedback: holistic thumbs-up/down learning signal.

Distinct from relevance/category overrides: a thumb has no AI baseline, so its mere
presence is the signal and clearing it removes the signal -- there is no net-change rule.
The spyglass-preferences skill reads list_feedback alongside the relevance/category overrides.
"""

from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Item

# The only values a thumb may hold: up, down, or cleared (None).
_VALID = {"up", "down", None}


def set_feedback(engine: Engine, card_id: int, feedback: str | None) -> dict | None:
    """Record (or clear) one card's thumbs feedback, pinning relevance for a thumb-down.

    feedback must be 'up', 'down', or None (clear). Sets feedback_at on a value and clears
    it on None. Returns {feedback, feedback_at} or None if the card is unknown. Raises
    ValueError for an invalid value.

    Relevance side effect: a thumb-down is a decisive OUT --
    it pins relevance='out' + override on this item (and, via the propagation model, sinks
    semantic neighbours). A thumb-up is a soft boost, NOT a level-setter, so it never pins a
    level here -- the item's displayed relevance still comes from the blended score, which the
    thumb lifts through self-similarity. Leaving the 'down' state (to 'up' or cleared) releases
    the OUT pin, reverting relevance to the AI baseline.
    """
    if feedback not in _VALID:
        raise ValueError(f"invalid feedback: {feedback!r}")
    now = datetime.now(UTC)
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            return None
        was_down = card.feedback == "down"
        card.feedback = feedback
        card.feedback_at = now if feedback is not None else None
        if feedback == "down":
            # Decisive OUT: pin this item out (an explicit label that wins on its own item).
            card.relevance = "out"
            card.relevance_override = True
            card.relevance_at = now
        elif was_down:
            # Transitioned away from down -> release the OUT pin, back to the AI baseline.
            card.relevance = card.relevance_ai
            card.relevance_override = False
            # If the card was never AI-scored, releasing must return it to genuinely unjudged
            # (relevance_at cleared) -- otherwise the timestamp left by the down-pin would make
            # it read as judged and surface a phantom blended level instead of "unjudged".
            card.relevance_at = None if card.relevance_ai is None else now
        card.updated_at = now
        session.add(card)
        session.commit()
        return {
            "feedback": card.feedback,
            "feedback_at": card.feedback_at.isoformat() if card.feedback_at else None,
        }


def list_feedback(engine: Engine) -> list[dict]:
    """Cards the user has thumbed -- the learning signal for the preferences skill.

    Each entry: card_id, title, feedback, relevance, category. Cleared (null) feedback never
    appears, mirroring how a reverted override drops out of list_overrides.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Card, Item)
            .where(Card.item_id == Item.id)
            .where(Card.feedback.is_not(None))  # type: ignore[union-attr]
        ).all()
    return [
        {
            "card_id": card.id,
            "title": item.title,
            "feedback": card.feedback,
            "relevance": card.relevance,
            "category": card.category,
        }
        for card, item in rows
    ]
