"""Tests for the category review tail: needs_review queue + confirm_category.

The centroid auto-categorizer is retired; the LLM enrichment pass now
assigns categories and uncategorized cards simply surface here for human assignment.
"""

from datetime import UTC, datetime

import numpy as np
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Card, CardState, Embedding, Item


def _engine(tmp_path):
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    return engine


def _seed_categorized(engine, ext_id, title, category, *, state=CardState.NEW, confirmed=False,
                      vector=None, dim=3):
    """Insert an Item + Card (+ optional Embedding) and return (item_id, card_id)."""
    with Session(engine) as s:
        item = Item(source="rss", external_id=ext_id, title=title, url="https://x.test")
        s.add(item)
        s.commit()
        s.refresh(item)
        card = Card(item_id=item.id, summary="", category=category, category_ai=category,
                    state=state, category_confirmed=confirmed)
        s.add(card)
        if vector is not None:
            v = np.asarray(vector, dtype=np.float32)
            v = v / (np.linalg.norm(v) or 1.0)
            s.add(Embedding(item_id=item.id, vector=v.tobytes(), model="fake", dim=dim,
                            text_source="shallow", embedded_at=datetime.now(UTC)))
        s.commit()
        s.refresh(card)
        return item.id, card.id


# ---------------------------------------------------------------------------
# needs_review: the uncategorized, non-dismissed review queue (no centroid arg).
# ---------------------------------------------------------------------------


def test_needs_review_lists_uncategorized(tmp_path):
    """needs_review surfaces uncategorized, non-dismissed cards with id/item_id/title."""
    from spyglass_service.autocategorize import needs_review
    engine = _engine(tmp_path)
    item_id, card_id = _seed_categorized(engine, "u", "Uncategorized", None)
    rows = needs_review(engine)
    assert len(rows) == 1
    assert rows[0] == {"card_id": card_id, "item_id": item_id, "title": "Uncategorized"}


def test_needs_review_excludes_categorized(tmp_path):
    """A card with a category is not in the review queue."""
    from spyglass_service.autocategorize import needs_review
    engine = _engine(tmp_path)
    _seed_categorized(engine, "c", "Categorized", "AI")
    assert needs_review(engine) == []


def test_needs_review_excludes_dismissed(tmp_path):
    """A dismissed (archived) uncategorized card is not in the review queue."""
    from spyglass_service.autocategorize import needs_review
    engine = _engine(tmp_path)
    _seed_categorized(engine, "d", "Dismissed", None, state=CardState.DISMISSED)
    assert needs_review(engine) == []


def test_needs_review_works_without_embedding(tmp_path):
    """needs_review no longer requires an embedding -- uncategorized cards surface regardless."""
    from spyglass_service.autocategorize import needs_review
    engine = _engine(tmp_path)
    _seed_categorized(engine, "noembed", "NoEmbed", None)  # no Embedding row
    rows = needs_review(engine)
    assert len(rows) == 1 and rows[0]["title"] == "NoEmbed"


# ---------------------------------------------------------------------------
# confirm_category: unchanged behavior (kept).
# ---------------------------------------------------------------------------


def test_confirm_category_still_works(tmp_path):
    """confirm_category sets the category and marks it confirmed."""
    from spyglass_service.autocategorize import confirm_category
    engine = _engine(tmp_path)
    _, card_id = _seed_categorized(engine, "a", "A", None)
    out = confirm_category(engine, card_id, "AI")
    assert out["category"] == "AI" and out["category_confirmed"] is True


def test_confirm_category_yep_keeps_value(tmp_path):
    """confirm_category with no new category flips only the confirmed flag (spot-check 'yep')."""
    from spyglass_service.autocategorize import confirm_category
    engine = _engine(tmp_path)
    _, card_id = _seed_categorized(engine, "a", "A", "AI", confirmed=False)
    out = confirm_category(engine, card_id)
    assert out == {"category": "AI", "category_confirmed": True, "category_override": False}
    with Session(engine) as s:
        assert s.get(Card, card_id).category_confirmed is True


def test_confirm_category_with_new_category_sets_override(tmp_path):
    """confirm_category(category=<value>) sets override=True when value differs from category_ai,
    and override=False when value matches category_ai. The new name is also registered in
    the Category table."""
    from spyglass_service.autocategorize import confirm_category
    from spyglass_service.categories import list_categories
    engine = _engine(tmp_path)
    # Case 1: new category differs from category_ai -> category_override=True
    _, card_id = _seed_categorized(engine, "a", "A", "AI", confirmed=False)  # category_ai == "AI"
    out = confirm_category(engine, card_id, "Health")                         # differs from category_ai
    assert out == {"category": "Health", "category_confirmed": True, "category_override": True}
    # The brand-new category name must now appear in the Category table.
    cat_names = [c["name"] for c in list_categories(engine)]
    assert "Health" in cat_names
    # Case 2: new category equals category_ai -> category_override=False
    _, card_id2 = _seed_categorized(engine, "b", "B", "Tech", confirmed=False)  # category_ai == "Tech"
    out2 = confirm_category(engine, card_id2, "Tech")                            # equals category_ai
    assert out2 == {"category": "Tech", "category_confirmed": True, "category_override": False}


def test_confirm_category_unknown_card_returns_none(tmp_path):
    """confirm_category returns None when the card_id does not exist."""
    from spyglass_service.autocategorize import confirm_category
    assert confirm_category(_engine(tmp_path), 9999) is None


def test_confirm_category_revert_to_ai_value(tmp_path):
    """confirm_category(category=category_ai) -> category_override=False, category_confirmed=True."""
    from spyglass_service.autocategorize import confirm_category
    engine = _engine(tmp_path)
    # Card currently has category="X", category_ai="AI"; confirming with "AI" reverts the override.
    with Session(engine) as s:
        item = Item(source="rss", external_id="rv", title="Revert", url="https://x.test")
        s.add(item)
        s.commit()
        s.refresh(item)
        card = Card(item_id=item.id, summary="", category="X", category_ai="AI",
                    category_override=True, category_confirmed=False)
        s.add(card)
        s.commit()
        s.refresh(card)
        card_id = card.id
    out = confirm_category(engine, card_id, "AI")
    assert out is not None
    assert out["category"] == "AI"
    assert out["category_override"] is False
    assert out["category_confirmed"] is True


# ---------------------------------------------------------------------------
# Sibling category-module behavior exercised alongside confirm_category (kept).
# ---------------------------------------------------------------------------


def test_set_user_category_marks_confirmed(tmp_path):
    """A manual set_user_category always marks the card as confirmed."""
    from spyglass_service.categories import set_user_category
    engine = _engine(tmp_path)
    _, card_id = _seed_categorized(engine, "a", "A", "AI", confirmed=False)
    set_user_category(engine, card_id, "Health")
    with Session(engine) as s:
        card = s.get(Card, card_id)
    assert card.category == "Health" and card.category_confirmed is True
    assert card.category_override is True   # differs from category_ai "AI"


def test_set_user_category_unknown_card_returns_none(tmp_path):
    """set_user_category returns None when the card_id does not exist."""
    from spyglass_service.categories import set_user_category
    assert set_user_category(_engine(tmp_path), 9999, "Health") is None


def test_apply_categories_confirmed_flag(tmp_path):
    """apply_categories with confirmed=True stamps category_confirmed; default leaves it False."""
    from spyglass_service.categories import CategoryResult, apply_categories
    engine = _engine(tmp_path)
    _, c1 = _seed_categorized(engine, "a", "A", None)
    _, c2 = _seed_categorized(engine, "b", "B", None)
    apply_categories(engine, [CategoryResult(c1, "AI")])                 # default: not confirmed
    apply_categories(engine, [CategoryResult(c2, "AI")], confirmed=True)  # confirmed
    with Session(engine) as s:
        assert s.get(Card, c1).category_confirmed is False
        assert s.get(Card, c2).category_confirmed is True
