"""Tests for the register's week counts and the whole-group actions (pause, rename, move, remove)."""

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import ItemEntity, WatchEntity
from spyglass_service.radar.watch import groups, registry

from .test_brief_seed import NOW_NAIVE, add_item, make_engine


def link(engine, entity_id: int, title: str, *, age_hours: float = 3, tier: str = "top") -> int:
    """Store an item and link it to an entity; returns the item id."""
    item_id = add_item(engine, title, age_hours=age_hours, tier=tier, score=70 if tier != "out" else 2)
    with Session(engine) as session:
        session.add(ItemEntity(item_id=item_id, entity_id=entity_id))
        session.commit()
    return item_id


def seed(engine) -> dict[str, int]:
    """Two groups: Endoscopy AI (two active names) and Regulators (one muted name)."""
    with Session(engine) as s:
        a = registry.create_entity(s, "Alpha Scopes", category="Endoscopy AI")
        b = registry.create_entity(s, "Beta Vision", category="Endoscopy AI")
        c = registry.create_entity(s, "Reg Agency", kind="regulator", category="Regulators", status="muted")
        return {"a": a.id, "b": b.id, "c": c.id}


# --- week counts -----------------------------------------------------------------------------


def test_week_count_counts_recent_items_not_judged_out_per_entity_and_group(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    shared = link(engine, ids["a"], "shared story")
    with Session(engine) as s:  # the same item also found by the group's other name
        s.add(ItemEntity(item_id=shared, entity_id=ids["b"]))
        s.commit()
    link(engine, ids["a"], "second story", age_hours=24 * 5)
    link(engine, ids["a"], "old story", age_hours=24 * 9)
    link(engine, ids["a"], "noise", tier="out")
    link(engine, ids["b"], "beta story")
    with Session(engine) as s:
        payload = registry.grouped(s, now=NOW_NAIVE)
    endo = payload["categories"][0]
    assert endo["name"] == "Endoscopy AI"
    counts = {e["name"]: e["week_count"] for e in endo["entities"]}
    assert counts == {"Alpha Scopes": 2, "Beta Vision": 2}
    assert endo["week_count"] == 3  # the shared item counts once for the group
    regulators = payload["categories"][1]
    assert regulators["week_count"] == 0 and regulators["entities"][0]["week_count"] == 0
    engine.dispose()


def test_grouped_marks_a_group_paused_only_when_every_name_is_muted(tmp_path) -> None:
    engine = make_engine(tmp_path)
    seed(engine)
    with Session(engine) as s:
        payload = registry.grouped(s)
    flags = {c["name"]: c["paused"] for c in payload["categories"]}
    assert flags == {"Endoscopy AI": False, "Regulators": True}
    engine.dispose()


# --- group actions ---------------------------------------------------------------------------


def test_pause_mutes_every_followed_name_and_resume_restores_them(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    with Session(engine) as s:
        groups.apply_group_action(s, "Endoscopy AI", "pause")
        statuses = {e.name: e.status for e in s.exec(select(WatchEntity)).all()}
        assert statuses["Alpha Scopes"] == statuses["Beta Vision"] == "muted"
        groups.apply_group_action(s, "Endoscopy AI", "resume")
        assert s.get(WatchEntity, ids["a"]).status == "active"
        assert s.get(WatchEntity, ids["b"]).status == "active"
        assert s.get(WatchEntity, ids["c"]).status == "muted"  # another group is untouched
    engine.dispose()


def test_pause_leaves_suggested_names_and_their_past_items_alone(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    item_id = link(engine, ids["a"], "kept story")
    with Session(engine) as s:
        registry.create_entity(s, "Maybe Co", category="Endoscopy AI", status="suggested")
        groups.apply_group_action(s, "Endoscopy AI", "pause")
        assert s.exec(select(WatchEntity).where(WatchEntity.name == "Maybe Co")).one().status == "suggested"
        assert s.exec(select(ItemEntity.item_id)).all() == [item_id]
    engine.dispose()


def test_rename_and_move_change_the_category_of_every_name_in_one_go(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    with Session(engine) as s:
        groups.apply_group_action(s, "Endoscopy AI", "rename", to="  Scope makers ")
        assert {s.get(WatchEntity, ids[k]).category for k in ("a", "b")} == {"Scope makers"}
        groups.apply_group_action(s, "Scope makers", "move", to="Regulators")  # merges into an existing group
        assert {s.get(WatchEntity, i).category for i in ids.values()} == {"Regulators"}
    engine.dispose()


def test_the_other_group_is_the_names_with_no_category(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        loose = registry.create_entity(s, "Loose Co")
        groups.apply_group_action(s, "Other", "rename", to="Tools")
        assert s.get(WatchEntity, loose.id).category == "Tools"
        groups.apply_group_action(s, "Tools", "move", to="Other")
        assert s.get(WatchEntity, loose.id).category == ""
    engine.dispose()


@pytest.mark.parametrize("bad", ["", "   ", "x" * 61, "two\nlines", "tab\there"])
def test_a_bad_category_name_is_refused_and_nothing_changes(tmp_path, bad) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    with Session(engine) as s:
        with pytest.raises(groups.GroupError):
            groups.apply_group_action(s, "Endoscopy AI", "rename", to=bad)
        assert s.get(WatchEntity, ids["a"]).category == "Endoscopy AI"
    engine.dispose()


def test_a_group_action_needs_an_existing_group_and_a_known_action(tmp_path) -> None:
    engine = make_engine(tmp_path)
    seed(engine)
    with Session(engine) as s:
        with pytest.raises(groups.GroupNotFound):
            groups.apply_group_action(s, "Nowhere", "pause")
        with pytest.raises(groups.GroupError):
            groups.apply_group_action(s, "Regulators", "explode")
        with pytest.raises(groups.GroupError):
            groups.apply_group_action(s, "Regulators", "move")  # no destination
    engine.dispose()


def test_remove_deletes_the_names_and_returns_them_with_their_links_for_undo(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    item_id = link(engine, ids["a"], "story")
    with Session(engine) as s:
        removed = groups.apply_group_action(s, "Endoscopy AI", "remove")
        assert {e["name"] for e in removed} == {"Alpha Scopes", "Beta Vision"}
        assert s.exec(select(WatchEntity.name)).all() == ["Reg Agency"]
        assert s.exec(select(ItemEntity)).all() == []
    alpha = next(e for e in removed if e["name"] == "Alpha Scopes")
    assert alpha["links"] == [{"item_id": item_id, "via": "query"}]
    engine.dispose()


def test_restore_recreates_removed_names_with_status_and_links_and_skips_duplicates(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    item_id = link(engine, ids["a"], "story")
    with Session(engine) as s:
        removed = groups.apply_group_action(s, "Endoscopy AI", "remove")
        assert groups.restore_entries(s, removed) == 2
        assert groups.restore_entries(s, removed) == 0  # already back
        alpha = s.exec(select(WatchEntity).where(WatchEntity.name == "Alpha Scopes")).one()
        assert alpha.category == "Endoscopy AI" and alpha.status == "active"
        assert s.exec(select(ItemEntity.item_id).where(ItemEntity.entity_id == alpha.id)).all() == [item_id]
    engine.dispose()


def test_restore_drops_links_to_items_that_no_longer_exist(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = seed(engine)
    link(engine, ids["a"], "story")
    with Session(engine) as s:
        removed = groups.apply_group_action(s, "Endoscopy AI", "remove")
        removed[0]["links"].append({"item_id": 9999, "via": "query"})
        groups.restore_entries(s, removed)
        assert all(link_.item_id != 9999 for link_ in s.exec(select(ItemEntity)).all())
    engine.dispose()


def test_restore_keeps_a_rejected_status(tmp_path) -> None:
    """An entry sent back to the register keeps "rejected", and its section and suggestion count."""
    engine = make_engine(tmp_path)
    entries = [{"name": "Gamma Optics", "status": "rejected", "section": "Competitors", "count": 4, "links": []}]
    with Session(engine) as s:
        assert groups.restore_entries(s, entries) == 1
        gamma = s.exec(select(WatchEntity).where(WatchEntity.name == "Gamma Optics")).one()
        assert (gamma.status, gamma.section, gamma.suggest_count) == ("rejected", "Competitors", 4)
    engine.dispose()


def _shown(session) -> list[str]:
    """The group names in the order the page shows them."""
    return [c["name"] for c in registry.grouped(session)["categories"]]


def test_move_up_and_down_swap_neighbours_and_stop_at_the_ends(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        for name, category in (("A1", "Alpha"), ("B1", "Beta"), ("C1", "Gamma")):
            registry.create_entity(s, name, category=category)
        assert groups.group_order(s) == []
        groups.apply_group_action(s, "Gamma", "up")
        assert _shown(s) == ["Alpha", "Gamma", "Beta"]
        groups.apply_group_action(s, "Alpha", "down")
        assert _shown(s) == ["Gamma", "Alpha", "Beta"]
        groups.apply_group_action(s, "Gamma", "up")  # already first: nothing moves
        groups.apply_group_action(s, "Beta", "down")  # already last: nothing moves
        assert _shown(s) == ["Gamma", "Alpha", "Beta"]
        assert groups.group_order(s) == ["Gamma", "Alpha", "Beta"]
        with pytest.raises(groups.GroupNotFound):
            groups.apply_group_action(s, "Nowhere", "up")
    engine.dispose()


def test_a_move_first_writes_the_order_as_shown(tmp_path) -> None:
    """An install that never ordered its groups gets the alphabetical order stored on the first move."""
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        for name, category in (("A1", "Alpha"), ("B1", "Beta"), ("E1", "")):
            registry.create_entity(s, name, category=category)
        groups.apply_group_action(s, "Alpha", "up")  # at the top: only the order is written
        assert groups.group_order(s) == ["Alpha", "Beta", "Other"]
        groups.apply_group_action(s, "Other", "up")
        assert groups.group_order(s) == ["Alpha", "Other", "Beta"]
    engine.dispose()


def test_rename_keeps_the_groups_place(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        for name, category in (("A1", "Alpha"), ("B1", "Beta"), ("C1", "Gamma")):
            registry.create_entity(s, name, category=category)
        groups.save_group_order(s, ["Gamma", "Alpha", "Beta"])
        groups.apply_group_action(s, "Alpha", "rename", to="Zulu")
        assert groups.group_order(s) == ["Gamma", "Zulu", "Beta"]
        assert _shown(s) == ["Gamma", "Zulu", "Beta"]
        groups.apply_group_action(s, "Zulu", "move", to="Beta")  # merging takes the existing group's place
        assert groups.group_order(s) == ["Gamma", "Beta"]
        assert _shown(s) == ["Gamma", "Beta"]
    engine.dispose()
