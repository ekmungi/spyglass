"""Managed categories: a persistent set + net-change override.

Categories unify the old curation `category` and organize `group_label` into one
concept. They live in their own table so an empty, newly created category survives
and stays selectable. The override state (value != the AI's value) is the learning
signal, self-clearing on revert.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.models import Card, Category, RunLog

# --- One-time category consolidation ---------------------------------------
# The approved broad set the user owns; the migration seeds these and reduces the registry to them.
CATEGORY_KEEP: list[str] = [
    "Healthcare AI",
    "LLMs & AI Research",
    "Agentic Systems",
    "AI Dev Tools & Skills",
    "Robotics",
    "Product & Career",
]
# Old drifted labels -> approved bucket (or None -> Unsorted). Labels already in CATEGORY_KEEP
# (Healthcare AI, Agentic Systems, Robotics) are left as-is and need no entry here.
CATEGORY_MIGRATION_MAP: dict[str, str | None] = {
    "Artificial Intelligence in Healthcare": "Healthcare AI",
    "AI in Healthcare": "Healthcare AI",
    "AI in Surgery": "Healthcare AI",
    "AI in Endoscopy": "Healthcare AI",
    "Large language models": "LLMs & AI Research",
    "AI Research": "LLMs & AI Research",
    "AI Safety": "LLMs & AI Research",
    "Developer Tools": "AI Dev Tools & Skills",
    "Open Source AI": "AI Dev Tools & Skills",
    "Business/Leadership": "Product & Career",
    "Career": "Product & Career",
    "Misc": None,
}
# RunLog marker so the seed+consolidate runs exactly once (the new version's first boot).
_CATEGORY_MIGRATE_MARKER = "category_migrate_v1"


@dataclass(frozen=True)
class CategoryResult:
    """One category assignment from the AI categorize pass."""

    card_id: int
    category: str


def _ensure_category(session: Session, name: str) -> None:
    """Register a category name in the managed set if it is not already present."""
    if session.exec(select(Category).where(Category.name == name)).first() is None:
        session.add(Category(name=name))


def add_category(engine: Engine, name: str) -> None:
    """Create an empty category that persists even with zero cards."""
    with Session(engine) as session:
        _ensure_category(session, name)
        session.commit()


def apply_categories(engine: Engine, results: list[CategoryResult], *, confirmed: bool = False) -> int:
    """AI pass: set each card's category + baseline, registering the name. Skips user-overridden
    cards. When confirmed=True (user-approved review) also marks category_confirmed. Returns
    how many were applied."""
    applied = 0
    with Session(engine) as session:
        for result in results:
            card = session.get(Card, result.card_id)
            if card is None or card.category_override:
                continue
            card.category = result.category
            card.category_ai = result.category
            card.category_override = False
            if confirmed:
                card.category_confirmed = True
            card.updated_at = datetime.now(UTC)
            _ensure_category(session, result.category)
            session.add(card)
            applied += 1
        session.commit()
    return applied


def set_user_category(engine: Engine, card_id: int, category: str) -> dict | None:
    """User recategorize: override only on a net change vs the AI value. A manual
    change anywhere confirms the card (category_confirmed=True).

    Returns the new {category, category_confirmed, category_override}, or None if unknown.
    """
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            return None
        card.category = category
        card.category_confirmed = True
        card.category_override = category != card.category_ai
        card.updated_at = datetime.now(UTC)
        _ensure_category(session, category)
        session.add(card)
        session.commit()
        return {
            "category": card.category,
            "category_confirmed": card.category_confirmed,
            "category_override": card.category_override,
        }


def delete_category(engine: Engine, name: str) -> bool:
    """Remove a managed category and re-bucket its cards to Unsorted.

    Deletes the registry row and clears the name from every card -- both `category` (so the
    card becomes Unsorted) and `category_ai` (so no stale AI baseline survives to reappear).
    Any override on a re-bucketed card is cleared, since there is no longer a label to override.

    Args:
        engine: The service database engine.
        name: The category name to remove.

    Returns:
        True when the category existed and was removed; False when the name is unknown.
    """
    with Session(engine) as session:
        row = session.exec(select(Category).where(Category.name == name)).first()
        if row is None:
            return False
        session.delete(row)
        for card in session.exec(select(Card).where(Card.category == name)).all():
            card.category = None
            card.category_override = False
            session.add(card)
        for card in session.exec(select(Card).where(Card.category_ai == name)).all():
            card.category_ai = None
            session.add(card)
        session.commit()
        return True


def rename_category(engine: Engine, old: str, new: str) -> bool:
    """Rename a managed category everywhere it appears.

    Both Card.category and Card.category_ai are renamed so the net-change
    override state is untouched. False when the old name is unknown.
    """
    with Session(engine) as session:
        row = session.exec(select(Category).where(Category.name == old)).first()
        if row is None:
            return False
        row.name = new
        session.add(row)
        for card in session.exec(select(Card).where(Card.category == old)).all():
            card.category = new
            session.add(card)
        for card in session.exec(select(Card).where(Card.category_ai == old)).all():
            card.category_ai = new
            session.add(card)
        session.commit()
        return True


def managed_category_names(engine: Engine) -> list[str]:
    """The managed category vocabulary -- just the registry (Category table), sorted.

    This is the closed set the enrichment call is constrained to. Unlike
    `list_categories`, it does NOT include stray labels still present on cards; only names the
    user (or the migration) has registered. Empty when no vocabulary is configured yet.
    """
    with Session(engine) as session:
        return sorted(c.name for c in session.exec(select(Category)).all())


def list_categories(engine: Engine) -> list[dict]:
    """All managed categories with card counts, empty ones included.
    Order: alphabetical by name (stable; position column kept dormant)."""
    with Session(engine) as session:
        managed = {c.name for c in session.exec(select(Category)).all()}
        rows = session.exec(
            select(Card.category, func.count())
            .where(Card.category.is_not(None))  # type: ignore[union-attr]
            .group_by(Card.category)
        ).all()
    counts = {name: count for name, count in rows}
    all_names = managed | set(counts)
    return sorted(
        ({"name": name, "count": counts.get(name, 0)} for name in all_names),
        key=lambda c: c["name"],
    )


def migrate_categories(
    engine: Engine, mapping: dict[str, str | None], keep: list[str]
) -> dict:
    """One-time consolidation of the drifted category labels onto the approved set.

    Seeds the approved `keep` set, then rewrites every card whose category is not already an
    approved name: a mapped old label becomes its target (or Unsorted when the target is None),
    and any label neither mapped nor approved is sent to Unsorted -- so afterwards every
    card.category is either an approved name or None. Each rewrite re-baselines category_ai to
    the new value and clears the override (a fresh, authoritative bucketing). Finally the registry
    is reduced to exactly `keep`. Idempotent: a second run finds no non-approved labels and no-ops.

    Args:
        engine: The service database engine.
        mapping: old label -> approved label, or None to send that label to Unsorted.
        keep: the approved category set (seeded and left as the sole registry contents).

    Returns:
        {"remapped": n, "unsorted": n, "seeded": len(keep)}.
    """
    keep_set = set(keep)
    remapped = unsorted = 0
    with Session(engine) as session:
        for name in keep:
            _ensure_category(session, name)
        cards = session.exec(
            select(Card).where(Card.category.is_not(None))  # type: ignore[union-attr]
        ).all()
        for card in cards:
            if card.category in keep_set:
                continue  # already an approved bucket -- leave it (and its override) alone
            new = mapping.get(card.category, None)  # unmapped label -> Unsorted
            card.category = new
            card.category_ai = new
            card.category_override = False
            session.add(card)
            if new is None:
                unsorted += 1
            else:
                remapped += 1
        # Any lingering category_ai that is not approved would let a stray reappear on revert.
        for card in session.exec(
            select(Card).where(Card.category_ai.is_not(None))  # type: ignore[union-attr]
        ).all():
            if card.category_ai not in keep_set:
                card.category_ai = None
                session.add(card)
        # Reduce the registry to exactly the approved set.
        for row in session.exec(select(Category)).all():
            if row.name not in keep_set:
                session.delete(row)
        session.commit()
    return {"remapped": remapped, "unsorted": unsorted, "seeded": len(keep)}


def migrate_categories_once(
    engine: Engine,
    *,
    mapping: dict[str, str | None] | None = None,
    keep: list[str] | None = None,
) -> dict | None:
    """Apply the category consolidation exactly once, then never again.

    Guarded by a RunLog marker so it runs on the first startup of the new version (seeding the
    approved set and folding the drifted labels onto it) but does NOT re-seed on later boots --
    otherwise a bucket the user removed in Settings would keep reappearing.

    Args:
        engine: The service database engine.
        mapping: Old-label -> approved-label map (defaults to CATEGORY_MIGRATION_MAP).
        keep: The approved set (defaults to CATEGORY_KEEP).

    Returns:
        The migrate_categories tally on the first run; None when already applied.
    """
    with Session(engine) as session:
        done = session.exec(
            select(RunLog).where(RunLog.source == _CATEGORY_MIGRATE_MARKER)
        ).first()
        if done is not None:
            return None
    result = migrate_categories(
        engine,
        mapping if mapping is not None else CATEGORY_MIGRATION_MAP,
        keep if keep is not None else CATEGORY_KEEP,
    )
    with Session(engine) as session:
        session.add(
            RunLog(
                source=_CATEGORY_MIGRATE_MARKER,
                status="ok",
                detail=str(result),
                finished_at=datetime.now(UTC),
            )
        )
        session.commit()
    return result


def migrate_group_label_to_category(engine: Engine) -> int:
    """One-time unify: copy group_label into category where category is
    empty, and register every resulting name. Idempotent. Returns cards updated."""
    updated = 0
    with Session(engine) as session:
        cards = session.exec(
            select(Card)
            .where(Card.category.is_(None))  # type: ignore[union-attr]
            .where(Card.group_label.is_not(None))  # type: ignore[union-attr]
        ).all()
        for card in cards:
            card.category = card.group_label
            _ensure_category(session, card.group_label)
            session.add(card)
            updated += 1
        existing = session.exec(
            select(Card.category).where(Card.category.is_not(None))  # type: ignore[union-attr]
        ).all()
        for name in {n for n in existing if n}:
            _ensure_category(session, name)
        session.commit()
    return updated
