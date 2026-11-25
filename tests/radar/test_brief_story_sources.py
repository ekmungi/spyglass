"""Regression tests: a story lists at most eight distinct publications, counts each publication
once (the same article stored twice included), and the reader can ask which items share a story."""

from types import SimpleNamespace

from sqlmodel import Session

from spyglass_service.radar.brief.compose import compose_brief
from spyglass_service.radar.brief.document import story_item_ids, story_members
from spyglass_service.radar.models import RadarBrief, dumps

from .test_brief_seed import NOW, add_item, make_engine

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)


def _llm(_messages, _schema):
    """A writer model that always answers."""
    return {"opening": "x"}


def test_sources_are_capped_at_eight_distinct_publications_and_counted_truly(tmp_path) -> None:
    """12 publications report one event (plus a duplicate copy): 8 listed, 12 counted."""
    engine = make_engine(tmp_path)
    try:
        lead = add_item(engine, "Big launch", score=95, event_key="launch", origin="Pub 0",
                        url="https://pub0.example/launch")
        others = [add_item(engine, f"Launch report {i}", score=90 - i, event_key="launch",
                           origin=f"Pub {i}", url=f"https://pub{i}.example/launch")
                  for i in range(1, 12)]
        copy = add_item(engine, "Launch report 1 (copy)", score=50, event_key="launch",
                        origin="Pub 1 mirror", url="https://www.PUB1.example/launch/?utm_source=x")
        doc = compose_brief(engine, SETTINGS, None, llm=_llm, now=NOW)
        top = doc["sections"][0]["stories"][0]
        assert top["item_id"] == lead
        assert top["source_count"] == 12
        assert len(top["sources"]) == 8
        listed = [s["item_id"] for s in top["sources"]]
        assert listed == [lead, *others[:7]]  # the lead, then the best-scored publications
        assert copy not in listed
        # Every member stays known to the no-repeat rule even when not listed.
        assert {lead, *others, copy} <= story_item_ids(doc)
    finally:
        engine.dispose()


def test_story_members_returns_what_the_reader_was_shown(tmp_path) -> None:
    """The other items of an item's story in the latest brief that contains it."""
    engine = make_engine(tmp_path)
    try:
        lead = add_item(engine, "Event", score=90, event_key="e", origin="A",
                        url="https://a.example/e")
        second = add_item(engine, "Event again", score=80, event_key="e", origin="B",
                          url="https://b.example/e")
        alone = add_item(engine, "Something else", score=70, origin="C")
        compose_brief(engine, SETTINGS, None, llm=_llm, now=NOW)
        with Session(engine) as session:
            assert story_members(session, lead) == [second]
            assert story_members(session, second) == [lead]
            assert story_members(session, alone) == []
            assert story_members(session, 99999) == []
    finally:
        engine.dispose()


def test_story_members_also_reads_the_unpicked_stories(tmp_path) -> None:
    """The other sources of an unpicked story come from the brief that lists it, as for a picked one."""
    engine = make_engine(tmp_path)
    try:
        doc = {"day": "2026-11-12", "sections": [{
            "key": "health",
            "stories": [{"item_id": 1, "sources": [{"item_id": 1, "name": "A"}]}],
            "more": [{"item_id": 7, "sources": [{"item_id": 7, "name": "B"}, {"item_id": 8, "name": "C"}]}],
        }]}
        with Session(engine) as session:
            session.add(RadarBrief(day="2026-11-12", doc=dumps(doc)))
            session.commit()
            assert story_members(session, 7) == [8]
            assert story_members(session, 8) == [7]
            assert story_members(session, 1) == []
    finally:
        engine.dispose()
