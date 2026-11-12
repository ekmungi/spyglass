"""Tests for the watch register."""

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import ItemEntity
from spyglass_service.radar.watch import registry

from .test_brief_seed import add_item, make_engine


def test_create_defaults_and_duplicate_detection(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        e = registry.create_entity(s, " Intuitive Surgical ", kind="company", category="Surgical robotics",
                                   aliases=["Intuitive", "intuitive surgical"])
        assert e.name == "Intuitive Surgical" and e.query == '"Intuitive Surgical"' and e.status == "active"
        assert registry.entity_dict(e)["aliases"] == ["Intuitive"]
        with pytest.raises(registry.DuplicateEntity):
            registry.create_entity(s, "intuitive  surgical")
        with pytest.raises(registry.DuplicateEntity):  # an alias of an existing entity
            registry.create_entity(s, "Intuitive")
    engine.dispose()


def test_create_validates_input(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        with pytest.raises(ValueError):
            registry.create_entity(s, "  ")
        with pytest.raises(ValueError):
            registry.create_entity(s, "X", kind="spaceship")
        with pytest.raises(ValueError):
            registry.create_entity(s, "X", status="deleted")
    engine.dispose()


def test_update_and_delete(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        a = registry.create_entity(s, "A", status="suggested")
        registry.create_entity(s, "B")
        changed = registry.update_entity(s, a.id, {"status": "active", "category": "X", "aliases": ["Aa"]})
        assert changed.status == "active" and changed.category == "X"
        assert registry.entity_dict(changed)["aliases"] == ["Aa"]
        assert registry.update_entity(s, 999, {"status": "muted"}) is None
        with pytest.raises(ValueError):
            registry.update_entity(s, a.id, {"status": "bogus"})
        with pytest.raises(registry.DuplicateEntity):
            registry.update_entity(s, a.id, {"name": "B"})
        item_id = add_item(engine, "x")
        s.add(ItemEntity(item_id=item_id, entity_id=a.id))
        s.commit()
        assert registry.delete_entity(s, a.id) is True
        assert registry.delete_entity(s, a.id) is False
        assert s.exec(select(ItemEntity)).all() == []
    engine.dispose()


def test_grouped_sorts_categories_limits_recent_and_separates_suggested(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        z = registry.create_entity(s, "Zeta", category="Imaging AI")
        registry.create_entity(s, "Alpha", category="Endoscopy AI")
        registry.create_entity(s, "Maybe", category="AI labs", status="suggested")
        ids = [add_item(engine, f"Zeta news {i}", age_hours=i + 1) for i in range(5)]
        hidden = add_item(engine, "Judged out", score=2, tier="out", age_hours=0.5)
        for i in [*ids, hidden]:
            s.add(ItemEntity(item_id=i, entity_id=z.id))
        s.commit()
        out = registry.grouped(s)
    assert [c["name"] for c in out["categories"]] == ["Endoscopy AI", "Imaging AI"]
    zeta = out["categories"][1]["entities"][0]
    assert [r["title"] for r in zeta["recent"]] == ["Zeta news 0", "Zeta news 1", "Zeta news 2"]
    assert [e["name"] for e in out["suggested"]] == ["Maybe"]
    engine.dispose()


def test_grouped_empty(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        assert registry.grouped(s) == {"categories": [], "suggested": []}
    engine.dispose()
