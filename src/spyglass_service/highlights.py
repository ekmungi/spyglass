"""Highlight store: anchored quotes per card.

Highlights belong to cards (not items): they are the user's reading capture,
deleted freely, and routed to Claude sessions via the get_highlights MCP tool.
"""

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Highlight


def _serialize(highlight: Highlight) -> dict:
    """Flatten one highlight for REST/MCP consumers."""
    return {
        "id": highlight.id,
        "card_id": highlight.card_id,
        "quote": highlight.quote,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "note": highlight.note,
        "created_at": highlight.created_at.isoformat(),
    }


def add_highlight(
    engine: Engine,
    card_id: int,
    quote: str,
    start_offset: int | None = None,
    end_offset: int | None = None,
    note: str | None = None,
) -> dict | None:
    """Store one highlight for a card; returns it serialized, or None for unknown cards.

    Offsets anchor the quote into the stored markdown; they are optional because
    the quote itself is the search fallback when offsets are missing or stale.
    """
    with Session(engine) as session:
        if session.get(Card, card_id) is None:
            return None
        highlight = Highlight(
            card_id=card_id,
            quote=quote,
            start_offset=start_offset,
            end_offset=end_offset,
            note=note,
        )
        session.add(highlight)
        session.commit()
        session.refresh(highlight)
        return _serialize(highlight)


def list_highlights(engine: Engine, card_id: int) -> list[dict]:
    """All highlights for a card, oldest first (reading order of creation)."""
    with Session(engine) as session:
        rows = session.exec(
            select(Highlight)
            .where(Highlight.card_id == card_id)
            .order_by(Highlight.created_at)  # type: ignore[arg-type]
        ).all()
    return [_serialize(row) for row in rows]


def delete_for_card(engine: Engine, card_id: int) -> int:
    """Remove every Highlight belonging to a card; return how many were deleted.

    Safe to call when the card has no highlights (returns 0). Used during
    hard-delete teardown before the Card row is removed.
    """
    with Session(engine) as session:
        rows = session.exec(select(Highlight).where(Highlight.card_id == card_id)).all()
        count = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()
    return count


def delete_highlight(engine: Engine, highlight_id: int) -> bool:
    """Remove one highlight; False when it does not exist."""
    with Session(engine) as session:
        highlight = session.get(Highlight, highlight_id)
        if highlight is None:
            return False
        session.delete(highlight)
        session.commit()
        return True
