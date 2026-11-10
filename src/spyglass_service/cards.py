"""Card materialization: every collected item gets an interactive card immediately.

Cards start uncurated (raw title/excerpt) so the dashboard is usable before any
Claude curation; curation later enriches these cards in place.
"""

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Item


def materialize_cards(engine: Engine) -> int:
    """Create an uncurated card for every item that does not have one yet.

    Returns the number of cards created. Idempotent: items that already have a
    card are skipped, so it is safe to run after every collection and on startup.
    """
    created = 0
    with Session(engine) as session:
        carded = set(session.exec(select(Card.item_id)).all())
        items = session.exec(select(Item).where(Item.id.not_in(carded))).all()  # type: ignore[union-attr]
        for item in items:
            session.add(
                Card(
                    item_id=item.id,
                    summary=item.summary or item.title,
                    curated=False,
                )
            )
            created += 1
        session.commit()
    return created
