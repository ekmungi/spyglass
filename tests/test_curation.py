"""Tests for the curation core: which items are pending, and enriching their cards."""

from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.cards import materialize_cards
from spyglass_service.curation import (
    CurationResult,
    apply_curation,
    assign_groups,
    get_pending_items,
    list_groups,
)
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, Item


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def add_item(engine, ext_id: str) -> int:
    with Session(engine) as session:
        item = Item(source="rss", external_id=ext_id, title=f"T {ext_id}", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


def test_pending_items_are_those_whose_card_is_uncurated(tmp_path: Path) -> None:
    """After collection every item has an uncurated card; those are the curation backlog."""
    engine = make_engine(tmp_path)
    add_item(engine, "a")
    add_item(engine, "b")
    materialize_cards(engine)
    pending = get_pending_items(engine)
    assert {p.external_id for p in pending} == {"a", "b"}


def test_curated_items_are_not_pending(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    add_item(engine, "b")
    materialize_cards(engine)
    apply_curation(engine, [CurationResult(item_id=a, summary="why", tags=["x"])])
    pending = get_pending_items(engine)
    assert [p.external_id for p in pending] == ["b"]


def test_apply_curation_enriches_the_existing_card(tmp_path: Path) -> None:
    """Curation updates the raw card in place: better summary, tags, curated flag."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    enriched = apply_curation(
        engine, [CurationResult(item_id=a, summary="why it matters", tags=["agentic-ai"])]
    )
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
    assert enriched == 1
    assert len(cards) == 1  # enriched, not duplicated
    assert cards[0].curated is True
    assert cards[0].summary == "why it matters"
    assert cards[0].tags == "agentic-ai"


def test_apply_curation_creates_a_card_when_missing(tmp_path: Path) -> None:
    """Defensive: a result for an item with no card yet still produces a curated card."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")  # no materialize -> no card yet
    enriched = apply_curation(engine, [CurationResult(item_id=a, summary="s", tags=[])])
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
    assert enriched == 1
    assert cards[0].curated is True


def test_apply_curation_stores_category(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    apply_curation(engine, [CurationResult(item_id=a, summary="s", category="Agentic AI")])
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
    assert card.category == "Agentic AI"


def test_ungrouped_only_excludes_already_grouped_items(tmp_path: Path) -> None:
    """The organize pass can batch through the whole feed: grouped items drop out."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    add_item(engine, "b")
    materialize_cards(engine)
    assign_groups(engine, {a: "Group A"})
    remaining = get_pending_items(engine, ungrouped_only=True)
    assert [p.external_id for p in remaining] == ["b"]


def test_uncategorized_only_excludes_categorized_items(tmp_path: Path) -> None:
    """The categorize pass batches the whole feed: categorized items drop out."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    add_item(engine, "b")
    materialize_cards(engine)
    from spyglass_service.categories import CategoryResult, apply_categories
    from spyglass_service.models import Card
    with Session(engine) as session:
        card_a = session.exec(select(Card).where(Card.item_id == a)).first()
    apply_categories(engine, [CategoryResult(card_id=card_a.id, category="Agentic AI")])
    remaining = get_pending_items(engine, uncategorized_only=True)
    assert [p.external_id for p in remaining] == ["b"]


def test_assign_groups_labels_cards(tmp_path: Path) -> None:
    """The organize pass labels cards with a cluster name without curating them."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    b = add_item(engine, "b")
    materialize_cards(engine)
    labelled = assign_groups(engine, {a: "Oncology", b: "Oncology"})
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
    assert labelled == 2
    assert {c.group_label for c in cards} == {"Oncology"}
    assert all(c.curated is False for c in cards)  # organizing is not curating


def test_list_groups_returns_labels_and_counts_largest_first(tmp_path: Path) -> None:
    """Existing groups are exposed so clustering stays stable across runs."""
    engine = make_engine(tmp_path)
    ids = [add_item(engine, x) for x in ("a", "b", "c")]
    materialize_cards(engine)
    assign_groups(engine, {ids[0]: "Agentic AI", ids[1]: "Agentic AI", ids[2]: "Oncology"})
    groups = list_groups(engine)
    assert groups == [{"group": "Agentic AI", "count": 2}, {"group": "Oncology", "count": 1}]


def test_apply_curation_ignores_unknown_item_ids(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    assert apply_curation(engine, [CurationResult(item_id=999, summary="s", tags=[])]) == 0


def test_apply_curation_keeps_the_category_when_none_is_given(tmp_path: Path) -> None:
    """A summary saved without a category must not wipe the card's category."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    apply_curation(engine, [CurationResult(item_id=a, summary="s", category="Agentic AI")])
    apply_curation(engine, [CurationResult(item_id=a, summary="newer summary")])
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
    assert card.summary == "newer summary"
    assert card.category == "Agentic AI"


def test_apply_curation_registers_the_category_and_records_it_as_ai(tmp_path: Path) -> None:
    """Like the enricher: a new category joins the managed set, and category_ai is set."""
    from spyglass_service.models import Category

    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    apply_curation(engine, [CurationResult(item_id=a, summary="s", category="Robotics")])
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
        names = [c.name for c in session.exec(select(Category)).all()]
    assert card.category_ai == "Robotics"
    assert "Robotics" in names


def test_apply_curation_respects_the_users_category(tmp_path: Path) -> None:
    """A category the user chose by hand (category_override) is not replaced."""
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
        card.category = "Mine"
        card.category_override = True
        session.add(card)
        session.commit()
    apply_curation(engine, [CurationResult(item_id=a, summary="s", category="Robotics")])
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
    assert card.category == "Mine"
    assert card.category_ai == "Robotics"


def test_apply_curation_keeps_a_category_the_user_confirmed(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    a = add_item(engine, "a")
    materialize_cards(engine)
    with Session(engine) as session:
        card = session.exec(select(Card)).first()
        card.category = "Confirmed"
        card.category_confirmed = True
        session.add(card)
        session.commit()
    apply_curation(engine, [CurationResult(item_id=a, summary="s", category="Robotics")])
    with Session(engine) as session:
        assert session.exec(select(Card)).first().category == "Confirmed"
