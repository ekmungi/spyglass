"""Managed categories: unify, net-change override, create-empty."""

from pathlib import Path

from sqlmodel import Session

from spyglass_service.categories import (
    CategoryResult,
    add_category,
    apply_categories,
    delete_category,
    list_categories,
    migrate_categories,
    migrate_categories_once,
    migrate_group_label_to_category,
    set_user_category,
)
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, Item


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


_seq = 0


def add_card(engine, group_label: str | None = None) -> int:
    global _seq
    _seq += 1
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"c{_seq}", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s", group_label=group_label)
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def get_card(engine, card_id: int) -> Card:
    with Session(engine) as session:
        return session.get(Card, card_id)


def names(engine) -> set[str]:
    return {c["name"] for c in list_categories(engine)}


def test_apply_categories_sets_value_baseline_and_registers_category(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    n = apply_categories(engine, [CategoryResult(card_id=card_id, category="Agentic AI")])
    card = get_card(engine, card_id)
    assert n == 1
    assert card.category == "Agentic AI"
    assert card.category_ai == "Agentic AI"
    assert "Agentic AI" in names(engine)


def test_apply_categories_skips_user_overridden(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=card_id, category="Agentic AI")])
    set_user_category(engine, card_id, "Healthcare AI")
    applied = apply_categories(engine, [CategoryResult(card_id=card_id, category="Infrastructure")])
    card = get_card(engine, card_id)
    assert applied == 0
    assert card.category == "Healthcare AI"


def test_set_user_category_net_change_then_revert(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=card_id, category="Agentic AI")])
    changed = set_user_category(engine, card_id, "Healthcare AI")
    assert changed["category_override"] is True
    set_user_category(engine, card_id, "Agentic AI")  # revert to AI value
    assert get_card(engine, card_id).category_override is False


def test_add_category_creates_empty_and_persists(tmp_path: Path) -> None:
    """A new category exists with zero cards and stays selectable."""
    engine = make_engine(tmp_path)
    add_category(engine, "New Topic")
    rows = list_categories(engine)
    new = next(c for c in rows if c["name"] == "New Topic")
    assert new["count"] == 0


def test_list_categories_counts_cards_and_keeps_empty(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    a, b = add_card(engine), add_card(engine)
    apply_categories(engine, [CategoryResult(a, "A"), CategoryResult(b, "A")])
    add_category(engine, "Empty")
    counts = {c["name"]: c["count"] for c in list_categories(engine)}
    assert counts["A"] == 2
    assert counts["Empty"] == 0


def test_migrate_group_label_to_category(tmp_path: Path) -> None:
    """Existing group_label values become categories (one-time unify)."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine, group_label="Oncology")
    migrate_group_label_to_category(engine)
    assert get_card(engine, card_id).category == "Oncology"
    assert "Oncology" in names(engine)


def test_delete_category_removes_it_and_rebuckets_cards_to_unsorted(tmp_path: Path) -> None:
    """Removing a category deletes the registry row and re-buckets its cards to Unsorted
    (both category and the AI baseline are cleared so no stale label survives)."""
    engine = make_engine(tmp_path)
    card_id = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=card_id, category="Robotics")])
    assert "Robotics" in names(engine)

    assert delete_category(engine, "Robotics") is True

    assert "Robotics" not in names(engine)
    card = get_card(engine, card_id)
    assert card.category is None
    assert card.category_ai is None
    assert card.category_override is False


def test_delete_category_unknown_returns_false(tmp_path: Path) -> None:
    """Deleting a name that is not in the managed set is a no-op returning False."""
    engine = make_engine(tmp_path)
    assert delete_category(engine, "Does Not Exist") is False


def test_migrate_categories_remaps_seeds_and_unsorts(tmp_path: Path) -> None:
    """One-time migration: map old dup labels onto the approved set, seed the set,
    send unmapped labels to Unsorted, and leave the registry holding only the approved names."""
    engine = make_engine(tmp_path)
    c_health = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c_health, category="AI in Surgery")])
    c_misc = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c_misc, category="Misc")])
    c_keep = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c_keep, category="Robotics")])

    mapping = {"AI in Surgery": "Healthcare AI", "Misc": None}
    keep = ["Healthcare AI", "Robotics"]
    result = migrate_categories(engine, mapping, keep)

    assert get_card(engine, c_health).category == "Healthcare AI"  # remapped dup
    assert get_card(engine, c_misc).category is None  # unmapped -> Unsorted
    assert get_card(engine, c_keep).category == "Robotics"  # already approved, kept
    assert names(engine) == {"Healthcare AI", "Robotics"}  # registry == the approved set
    assert result["remapped"] >= 1 and result["unsorted"] >= 1


def test_migrate_categories_is_idempotent(tmp_path: Path) -> None:
    """Running the migration twice changes nothing the second time (old labels already gone)."""
    engine = make_engine(tmp_path)
    c = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c, category="AI in Healthcare")])
    mapping = {"AI in Healthcare": "Healthcare AI"}
    keep = ["Healthcare AI"]
    migrate_categories(engine, mapping, keep)
    second = migrate_categories(engine, mapping, keep)
    assert get_card(engine, c).category == "Healthcare AI"
    assert names(engine) == {"Healthcare AI"}
    assert second["remapped"] == 0 and second["unsorted"] == 0


def test_migrate_categories_clears_stray_labels_not_in_keep(tmp_path: Path) -> None:
    """A card carrying a label that is neither in the mapping nor the approved set is sent to
    Unsorted, so post-migration every card.category is either approved or None."""
    engine = make_engine(tmp_path)
    c = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c, category="Some Old Label")])
    migrate_categories(engine, mapping={}, keep=["Healthcare AI"])
    assert get_card(engine, c).category is None
    assert names(engine) == {"Healthcare AI"}


def test_migrate_categories_once_runs_a_single_time(tmp_path: Path) -> None:
    """The seed+consolidate migration runs on the first call and is guarded thereafter, so a
    later user edit (e.g. removing a bucket) is never undone by a re-seed on restart."""
    engine = make_engine(tmp_path)
    c = add_card(engine)
    apply_categories(engine, [CategoryResult(card_id=c, category="AI in Surgery")])

    first = migrate_categories_once(
        engine, mapping={"AI in Surgery": "Healthcare AI"}, keep=["Healthcare AI"]
    )
    assert first is not None
    assert get_card(engine, c).category == "Healthcare AI"

    second = migrate_categories_once(
        engine, mapping={"AI in Surgery": "Healthcare AI"}, keep=["Healthcare AI"]
    )
    assert second is None  # guarded -- does not run (or re-seed) again


def test_list_categories_returns_alphabetical_order(tmp_path: Path) -> None:
    """list_categories is sorted by name (stable default; position dormant)."""
    engine = make_engine(tmp_path)
    for name in ("Robotics", "Infra", "Healthcare AI"):
        add_category(engine, name)
    ordered = [c["name"] for c in list_categories(engine)]
    assert ordered == ["Healthcare AI", "Infra", "Robotics"]
