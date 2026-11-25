"""Tests for the watch register."""

import pytest
from sqlmodel import Session, select

from spyglass_service.radar import feed_views, profile_defaults
from spyglass_service.radar.models import ItemEntity
from spyglass_service.radar.watch import groups, registry, review

from .test_brief_seed import NOW_NAIVE, add_item, make_engine


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
        maybe = registry.create_entity(s, "Maybe", category="AI labs", status="suggested")
        maybe.section = "health"  # placed by a collection cycle, so it is shown
        s.add(maybe)
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
        picture = registry.grouped(s)
        assert picture["categories"] == [] and picture["suggested"] == [] and picture["rejected"] == []
        assert picture["sections"] and set(picture["sections"][0]) == {"key", "label"}
    engine.dispose()


def test_rejected_names_are_not_followed(tmp_path) -> None:
    """A name the reader rejected is in no group, no followed-only list, no week count and no review."""
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        followed = registry.create_entity(s, "Alpha Scopes", category="Endoscopy AI")
        rejected = registry.create_entity(s, "Beta Vision", category="Endoscopy AI", status="rejected")
        followed_id, rejected_id = followed.id, rejected.id
    assert registry.STATUSES == ("active", "suggested", "muted", "rejected")
    assert registry.FOLLOWED == ("active", "muted")
    for entity_id, title in ((followed_id, "alpha story"), (rejected_id, "beta story")):
        item_id = add_item(engine, title, age_hours=3, tier="top", score=70)
        with Session(engine) as s:
            s.add(ItemEntity(item_id=item_id, entity_id=entity_id))
            s.commit()
    with Session(engine) as s:
        payload = registry.grouped(s, now=NOW_NAIVE)
        in_groups = [e["name"] for c in payload["categories"] for e in c["entities"]]
        assert in_groups == ["Alpha Scopes"]
        assert payload["suggested"] == []
        assert [e.name for e in groups.members(s, "Endoscopy AI", followed_only=True)] == ["Alpha Scopes"]
        assert len(feed_views.watch_group_item_ids(s, "Endoscopy AI", NOW_NAIVE)) == 1
        assert [r["name"] for r in review.build_picture(s)["register"]] == ["Alpha Scopes"]
    engine.dispose()


def test_entity_dict_carries_the_section_and_the_suggestion_count(tmp_path) -> None:
    """The register entry shows which section a name sits in and how often it was suggested."""
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        entity = registry.create_entity(s, "Alpha Scopes")
        assert registry.entity_dict(entity)["section"] == ""
        assert registry.entity_dict(entity)["count"] == 0
        entity.section, entity.suggest_count = "Competitors", 3
        shown = registry.entity_dict(entity)
        assert (shown["section"], shown["count"]) == ("Competitors", 3)
    engine.dispose()


def test_update_can_reject_a_name_and_an_unknown_status_is_refused(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        entity = registry.create_entity(s, "Alpha Scopes", status="suggested")
        assert registry.update_entity(s, entity.id, {"status": "rejected"}).status == "rejected"
        with pytest.raises(ValueError):
            registry.update_entity(s, entity.id, {"status": "banned"})
    engine.dispose()


def test_grouped_uses_the_stored_order_then_the_alphabet(tmp_path) -> None:
    """Groups named in the stored order come first, in that order; the rest follow alphabetically."""
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        for name, category in (("A1", "Alpha"), ("B1", "Beta"), ("C1", "Gamma"), ("D1", "Delta"), ("E1", "")):
            registry.create_entity(s, name, category=category)
        registry.create_entity(s, "Held", category="Muted only", status="suggested")
        assert [c["name"] for c in registry.grouped(s)["categories"]] == ["Alpha", "Beta", "Delta", "Gamma", "Other"]
        groups.save_group_order(s, ["Gamma", "Missing", "Other", "Alpha"])
        assert groups.group_order(s) == ["Gamma", "Missing", "Other", "Alpha"]
        shown = [c["name"] for c in registry.grouped(s)["categories"]]
        assert shown == ["Gamma", "Other", "Alpha", "Beta", "Delta"]
    engine.dispose()


def test_a_suggestion_no_collection_has_placed_is_not_listed(tmp_path) -> None:
    """An older mention-based suggestion (no topic, no section) waits for the first cycle to place it.

    Until then it is in neither `suggested` nor any count, so the page cannot show it or hide it.
    """
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        for name in ("Legacy One", "Legacy Two"):
            registry.create_entity(s, name, status="suggested", added_via="discovered", why="named in 3 relevant items")
        placed = registry.create_entity(s, "Placed Co", status="suggested", added_via="discovered")
        placed.section, placed.suggest_count = "health", 4
        s.add(placed)
        s.commit()
        registry.create_entity(s, "Found Co", status="suggested", added_via="discovered", topic="RSNA")
        picture = registry.grouped(s)
        assert [e["name"] for e in picture["suggested"]] == ["Found Co", "Placed Co"]
    engine.dispose()


def test_grouped_returns_rejected_names_and_profile_sections(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        registry.create_entity(s, "Zed Labs", category="Endoscopy AI", status="rejected")
        registry.create_entity(s, "Abe Labs", category="Endoscopy AI", status="rejected")
        held = registry.create_entity(s, "Maybe Co", status="suggested")
        held.section, held.suggest_count = "Competitors", 2
        s.add(held)
        s.commit()
        picture = registry.grouped(s)
        assert [r["name"] for r in picture["rejected"]] == ["Abe Labs", "Zed Labs"]
        assert picture["rejected"][0]["status"] == "rejected"
        assert picture["categories"] == []
        assert [(x["name"], x["section"], x["count"]) for x in picture["suggested"]] == [("Maybe Co", "Competitors", 2)]
        assert all(set(x) == {"key", "label"} for x in picture["sections"])
        assert picture["sections"] == [
            {"key": x["key"], "label": x["label"]} for x in profile_defaults.load_profile(s)["sections"]
        ]
    engine.dispose()
