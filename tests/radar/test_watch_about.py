"""Regression tests: a story carries a watch label only when it actually names the organisation.

A regulator's broad news search returns general news, so being found by an organisation's search
is not enough. These cases come from a real brief that labelled unrelated stories.
"""

from types import SimpleNamespace

from sqlmodel import Session, select

from spyglass_service.radar.brief.compose import compose_brief
from spyglass_service.radar.models import ItemEntity, WatchEntity
from spyglass_service.radar.watch import registry
from spyglass_service.radar.watch.registry import is_about

from .test_brief_seed import NOW, add_item, make_engine

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)


def test_unrelated_stories_found_by_a_regulator_search_are_not_about_it() -> None:
    """The three mislabelled stories from the real brief."""
    oura = "Oura buys AI primary-care start-up Counsel Health"
    a2z = "a2z Radiology AI gets EU MDR certification"
    for title in (oura, a2z):
        assert not is_about(["NICE"], title=title)
        assert not is_about(["HAS"], title=title)
    assert not is_about(["Recursion Pharmaceuticals", "Recursion"], title="AlphaGenome 2")


def test_short_names_and_acronyms_match_only_with_their_own_capitals() -> None:
    """NICE and HAS are not the English words "nice" and "has"."""
    assert is_about(["NICE"], title="NICE recommends an AI tool for skin cancer triage")
    assert not is_about(["NICE"], title="Nice results for a new colonoscopy model")
    assert not is_about(["NICE"], title="A nice day for robots")
    assert is_about(["HAS"], title="HAS publishes guidance on digital medical devices")
    assert not is_about(["HAS"], title="The company has raised new funds")
    assert not is_about(["FDA"], title="fda-style rules elsewhere")
    assert is_about(["FDA"], title="FDA clears an endoscopy detector")


def test_longer_names_match_whole_words_in_any_case() -> None:
    """Long names ignore case but still need whole words."""
    assert is_about(["Recursion Pharmaceuticals"], title="recursion pharmaceuticals cuts staff")
    assert is_about(["Olympus"], title="OLYMPUS opens a new plant")
    assert not is_about(["Olympus"], title="Olympusville council meets")


def test_the_headline_and_the_named_organisations_count_too() -> None:
    """A mention in the assessment headline or in its entity list is enough."""
    assert is_about(["NICE"], title="New guidance on AI devices", headline="NICE backs AI triage")
    assert is_about(["NICE"], title="New guidance on AI devices", entities=["NICE"])
    assert is_about(["Recursion Pharmaceuticals", "Recursion"], title="Drug pipeline update",
                    entities=["Recursion"])
    assert not is_about(["NICE"], title="New guidance", entities=["Nice"])


def _entity(session: Session, name: str, kind: str = "regulator", aliases=()) -> WatchEntity:
    """Add an active watch entity."""
    return registry.create_entity(session, name, kind=kind, category="Regulators",
                                  aliases=list(aliases))


def test_brief_drops_the_label_for_search_links_without_a_mention(tmp_path) -> None:
    """The Oura story keeps its search link but gets no watch label and no watch slot."""
    engine = make_engine(tmp_path)
    try:
        oura = add_item(engine, "Oura buys AI primary-care start-up Counsel Health", score=70)
        nice_story = add_item(engine, "NICE recommends an AI tool for skin cancer triage",
                              score=70, entities=["NICE"])
        with Session(engine) as session:
            nice, has = _entity(session, "NICE"), _entity(session, "HAS")
            for item_id in (oura, nice_story):
                for entity in (nice, has):
                    session.add(ItemEntity(item_id=item_id, entity_id=entity.id, via="query"))
            session.commit()
        doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
        stories = {st["item_id"]: (sec["key"], st) for sec in doc["sections"]
                   for st in sec["stories"]}
        assert stories[oura][1]["watch"] == [] and stories[oura][0] != "watch"
        assert stories[nice_story][0] == "watch"
        assert stories[nice_story][1]["watch"] == [{"name": "NICE", "category": "Regulators"}]
        with Session(engine) as session:
            assert len(session.exec(select(ItemEntity).where(ItemEntity.item_id == oura)).all()) == 2
    finally:
        engine.dispose()


def test_watch_page_lists_only_items_about_the_organisation(tmp_path) -> None:
    """Under Recursion Pharmaceuticals the AlphaGenome story is not listed."""
    engine = make_engine(tmp_path)
    try:
        unrelated = add_item(engine, "AlphaGenome 2", score=70, age_hours=1)
        related = add_item(engine, "Recursion Pharmaceuticals trims its pipeline", score=70,
                           age_hours=2)
        with Session(engine) as session:
            rec = _entity(session, "Recursion Pharmaceuticals", kind="company",
                          aliases=["Recursion"])
            for item_id in (unrelated, related):
                session.add(ItemEntity(item_id=item_id, entity_id=rec.id, via="query"))
            session.commit()
            out = registry.grouped(session)
        recent = out["categories"][0]["entities"][0]["recent"]
        assert [r["id"] for r in recent] == [related]
    finally:
        engine.dispose()
