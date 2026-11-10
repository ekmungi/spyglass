"""Curation core: which items still need Claude, and enriching their cards."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.categories import _ensure_category
from spyglass_service.models import Card, Item


@dataclass(frozen=True)
class CurationResult:
    """One enriched item from a Claude curation run."""

    item_id: int
    summary: str
    tags: list[str] = field(default_factory=list)
    category: str | None = None


def get_pending_items(
    engine: Engine, ungrouped_only: bool = False, uncategorized_only: bool = False
) -> list[Item]:
    """Items still needing Claude. Default: not yet curated. uncategorized_only: not
    yet categorized (the categorize pass batches the whole feed -- each categorized
    batch drops out). ungrouped_only: legacy, not yet grouped.
    """
    with Session(engine) as session:
        if uncategorized_only:
            categorized_ids = select(Card.item_id).where(Card.category.is_not(None))  # type: ignore[union-attr]
            statement = select(Item).where(Item.id.not_in(categorized_ids))  # type: ignore[union-attr]
        elif ungrouped_only:
            grouped_ids = select(Card.item_id).where(Card.group_label.is_not(None))  # type: ignore[union-attr]
            statement = select(Item).where(Item.id.not_in(grouped_ids))  # type: ignore[union-attr]
        else:
            # Not yet curated: items with no curated card (incl. cardless, defensively).
            curated_item_ids = select(Card.item_id).where(Card.curated == True)  # noqa: E712
            statement = select(Item).where(Item.id.not_in(curated_item_ids))  # type: ignore[union-attr]
        return list(session.exec(statement).all())


def apply_curation(engine: Engine, results: list[CurationResult]) -> int:
    """Enrich each result's card in place (summary, tags, curated=True).

    Returns how many cards were enriched. Unknown item ids are ignored; an item
    with no card yet gets one (defensive -- normally cards already exist).
    """
    enriched = 0
    with Session(engine) as session:
        known_ids = set(session.exec(select(Item.id)).all())
        for result in results:
            if result.item_id not in known_ids:
                continue
            card = session.exec(
                select(Card).where(Card.item_id == result.item_id)
            ).first()
            if card is None:
                card = Card(item_id=result.item_id, summary=result.summary)
            card.summary = result.summary
            card.tags = ",".join(result.tags) if result.tags else None
            # No category given keeps the card's; a given one joins the managed set
            # and is recorded as the AI's, but never replaces one the user chose or confirmed.
            if result.category:
                _ensure_category(session, result.category)
                card.category_ai = result.category
                if not card.category_override and not card.category_confirmed:
                    card.category = result.category
            card.curated = True
            card.updated_at = datetime.now(UTC)
            session.add(card)
            enriched += 1
        session.commit()
    return enriched


def list_groups(engine: Engine) -> list[dict]:
    """Existing group labels and their counts, largest first.

    Passed to Claude before organizing so new items are dropped into existing
    groups (stable clustering) instead of inventing fresh labels each run.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Card.group_label, func.count())
            .where(Card.group_label.is_not(None))  # type: ignore[union-attr]
            .group_by(Card.group_label)
        ).all()
    return sorted(
        [{"group": label, "count": count} for label, count in rows],
        key=lambda g: -g["count"],
    )


def assign_groups(engine: Engine, mapping: dict[int, str]) -> int:
    """Assign a cluster label to each item's card (the 'organize into groups' pass).

    This does not curate; it only labels cards so the dashboard can group similar
    items. Returns how many cards were labelled. Unknown items are skipped.
    """
    labelled = 0
    with Session(engine) as session:
        for item_id, group in mapping.items():
            card = session.exec(select(Card).where(Card.item_id == item_id)).first()
            if card is None:
                continue
            card.group_label = group
            card.updated_at = datetime.now(UTC)
            session.add(card)
            labelled += 1
        session.commit()
    return labelled
