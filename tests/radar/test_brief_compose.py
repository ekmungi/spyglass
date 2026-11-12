"""Tests for composing and storing a day's brief."""

from datetime import timedelta
from types import SimpleNamespace

from sqlmodel import Session, select

from spyglass_service.models import Feed, Item
from spyglass_service.radar.brief.compose import briefed_item_ids, brief_tz, compose_brief, local_today
from spyglass_service.radar.brief.document import fallback_opening, refresh_states
from spyglass_service.radar.models import ItemState, RadarBrief, loads

from .test_brief_seed import NOW, add_item, make_engine, make_index

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)


def stories_of(doc: dict) -> dict[str, list[dict]]:
    """Section key -> stories."""
    return {s["key"]: s["stories"] for s in doc["sections"]}


def test_compose_builds_the_contract_document_and_stores_it(tmp_path) -> None:
    engine = make_engine(tmp_path)
    for i, section in enumerate(("health", "models", "labs", "agents")):
        add_item(engine, f"Big news {i}", score=90 - i, age_hours=2 + i, section=section)
    calls = []

    def llm(messages, schema):
        calls.append(messages)
        return {"opening": "Four things happened. They matter."}

    doc = compose_brief(engine, SETTINGS, None, llm=llm, now=NOW)
    assert doc["day"] == "2026-11-12"
    assert doc["opening"] == "Four things happened. They matter."
    assert doc["quiet"] is False
    assert doc["read_minutes"] >= 1
    assert [s["key"] for s in doc["sections"]] == ["top"]
    story = doc["sections"][0]["stories"][0]
    assert story["id"] == f"s-{story['item_id']}" and story["why"] == "Matters for the reader."
    assert set(story) >= {"headline", "section_label", "kind", "score", "signal", "entities",
                          "published_at", "from_user", "source_count", "sources", "state"}
    assert "Big news 0" in calls[0][1]["content"]
    with Session(engine) as session:
        row = session.exec(select(RadarBrief)).one()
        assert row.day == "2026-11-12" and row.story_count == 4
        assert loads(row.doc)["opening"] == doc["opening"]
    engine.dispose()


def test_failing_or_missing_llm_never_fails_the_brief(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "Only story", score=80)

    def boom(messages, schema):
        raise RuntimeError("model is down")

    doc = compose_brief(engine, SETTINGS, None, llm=boom, now=NOW)
    assert "Only story" in doc["opening"]
    blank = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "  "}, now=NOW)
    assert blank["opening"]
    no_key = compose_brief(engine, SETTINGS, None, now=NOW)  # no key configured at all
    assert no_key["opening"]
    engine.dispose()


def test_two_publications_of_one_event_make_one_story_with_both_sources(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "Company launches robot", score=85, event_key="robot-launch", origin="STAT")
    add_item(engine, "Robot launched by company", score=70, event_key="robot-launch", origin="Reuters")
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    all_stories = [s for sec in doc["sections"] for s in sec["stories"]]
    assert len(all_stories) == 1
    assert all_stories[0]["source_count"] == 2
    assert {src["name"] for src in all_stories[0]["sources"]} == {"STAT", "Reuters"}
    engine.dispose()


def test_near_duplicate_embeddings_merge_into_one_story(tmp_path) -> None:
    engine = make_engine(tmp_path)
    a = add_item(engine, "Story A", score=80, origin="One")
    b = add_item(engine, "Story B reworded", score=60, origin="Two")
    c = add_item(engine, "Different thing", score=75, origin="Three")
    index = make_index({a: [1, 0, 0, 0], b: [0.99, 0.05, 0, 0], c: [0, 1, 0, 0]})
    doc = compose_brief(engine, SETTINGS, index, llm=lambda m, s: {"opening": "x"}, now=NOW)
    counts = sorted(s["source_count"] for sec in doc["sections"] for s in sec["stories"])
    assert counts == [1, 2]
    engine.dispose()


def test_nothing_is_repeated_from_the_previous_briefs(tmp_path) -> None:
    engine = make_engine(tmp_path)
    first = [add_item(engine, f"Monday news {i}", score=85, age_hours=5) for i in range(3)]
    llm = lambda m, s: {"opening": "x"}  # noqa: E731
    day1 = compose_brief(engine, SETTINGS, None, llm=llm, now=NOW)
    shown1 = {s["item_id"] for sec in day1["sections"] for s in sec["stories"]}
    assert shown1 == set(first)
    fresh = add_item(engine, "Tuesday news", score=88, age_hours=1)
    day2 = compose_brief(engine, SETTINGS, None, "2026-11-13", llm=llm, now=NOW + timedelta(days=1))
    shown2 = {s["item_id"] for sec in day2["sections"] for s in sec["stories"]}
    assert shown2 == {fresh}
    with Session(engine) as session:
        assert briefed_item_ids(session, "2026-11-13") == set(first)
        assert briefed_item_ids(session, "2026-11-12") == set()  # the day itself is not "previous"
    engine.dispose()


def test_regenerating_a_day_replaces_it_and_can_show_the_same_items(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "News", score=85)
    llm = lambda m, s: {"opening": "x"}  # noqa: E731
    compose_brief(engine, SETTINGS, None, llm=llm, now=NOW)
    again = compose_brief(engine, SETTINGS, None, llm=llm, now=NOW)
    assert sum(len(s["stories"]) for s in again["sections"]) == 1
    with Session(engine) as session:
        assert len(session.exec(select(RadarBrief)).all()) == 1
    engine.dispose()


def test_from_user_items_always_appear_even_unassessed_or_out(tmp_path) -> None:
    engine = make_engine(tmp_path)
    unassessed = add_item(engine, "Link I sent", score=None, from_user=True)
    rejected = add_item(engine, "Link judged out", score=5, tier="out", from_user=True)
    add_item(engine, "Not mine and out", score=5, tier="out")
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    mine = {s["item_id"] for s in stories_of(doc)["from_you"]}
    assert mine == {unassessed, rejected}
    assert all(s["from_user"] for s in stories_of(doc)["from_you"])
    engine.dispose()


def test_eligibility_filters(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ok = add_item(engine, "Fine", score=80)
    add_item(engine, "Too old", score=90, age_hours=24 * 6)
    add_item(engine, "Judged out", score=3, tier="out")
    add_item(engine, "Hidden", score=90, hidden=True)
    add_item(engine, "Not yet assessed", score=None)
    disabled = add_item(engine, "From a disabled feed", score=90)
    undated = add_item(engine, "No publish date", score=70, published=False, age_hours=5)
    with Session(engine) as session:
        session.add(Feed(feed_url="https://x.test/feed", name="X", kind="rss", enabled=False, added_via="manual"))
        item = session.get(Item, disabled)
        item.feed_url = "https://x.test/feed"
        session.add(item)
        session.commit()
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    shown = {s["item_id"] for sec in doc["sections"] for s in sec["stories"]}
    assert shown == {ok, undated}
    engine.dispose()


def test_empty_database_gives_an_honest_empty_quiet_brief(tmp_path) -> None:
    engine = make_engine(tmp_path)
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    assert doc["quiet"] is True and doc["sections"] == [] and doc["read_minutes"] == 1
    engine.dispose()


def test_quiet_day_says_so_and_is_not_padded(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "Lone top", score=80)
    for i in range(3):
        add_item(engine, f"Minor {i}", score=30, tier="skim")
    prompts = []

    def llm(messages, schema):
        prompts.append(messages[1]["content"])
        return {"opening": "A quiet day."}

    doc = compose_brief(engine, SETTINGS, None, llm=llm, now=NOW)
    assert doc["quiet"] is True
    assert len(stories_of(doc)["top"]) == 1 and len(stories_of(doc)["skim"]) == 3
    assert "quiet" in prompts[0]
    engine.dispose()


def test_collected_and_filtered_out_counts(tmp_path) -> None:
    engine = make_engine(tmp_path)
    for i in range(3):
        add_item(engine, f"Kept {i}", score=85)
    for i in range(7):
        add_item(engine, f"Dropped {i}", score=5, tier="out")
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    assert doc["collected"] == 10 and doc["filtered_out"] == 7
    engine.dispose()


def _watch(engine, item_id: int, name: str, kind: str, category: str, status: str = "active") -> None:
    """Register a watch entity and link the item to it."""
    from spyglass_service.radar.models import ItemEntity, WatchEntity

    with Session(engine) as session:
        entity = WatchEntity(name=name, kind=kind, category=category, status=status)
        session.add(entity)
        session.commit()
        session.add(ItemEntity(item_id=item_id, entity_id=entity.id))
        session.commit()


def test_company_and_regulator_stories_are_placed_in_the_watch_section(tmp_path) -> None:
    engine = make_engine(tmp_path)
    company = add_item(engine, "Rival raises money", score=60, tier="notable")
    regulator = add_item(engine, "The Agency clears a device", score=60, tier="notable")
    _watch(engine, company, "Rival", "company", "Surgical robotics")
    _watch(engine, regulator, "The Agency", "regulator", "Regulators")
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    watch = stories_of(doc)["watch"]
    assert {s["item_id"] for s in watch} == {company, regulator}
    assert doc["sections"][[s["key"] for s in doc["sections"]].index("watch")]["title"] == "On your watch list"
    rival = next(s for s in watch if s["item_id"] == company)
    assert rival["watch"] == [{"name": "Rival", "category": "Surgical robotics"}]
    engine.dispose()


def test_lab_journal_and_muted_entities_stay_out_of_the_watch_section(tmp_path) -> None:
    engine = make_engine(tmp_path)
    lab = add_item(engine, "Frontier Lab reports its finances", score=70, tier="notable")
    journal = add_item(engine, "The Journal publishes a study", score=65, tier="notable")
    muted = add_item(engine, "Quiet Co company news", score=62, tier="notable")
    _watch(engine, lab, "Frontier Lab", "lab", "AI labs")
    _watch(engine, journal, "The Journal", "publication", "Journals")
    _watch(engine, muted, "Quiet Co", "company", "Misc", status="muted")
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    sections = stories_of(doc)
    assert "watch" not in sections
    shown = {s["item_id"]: s for sec in sections.values() for s in sec}
    assert set(shown) == {lab, journal, muted}
    # The interface can still say which watched organisation a normal story is about.
    assert shown[lab]["watch"] == [{"name": "Frontier Lab", "category": "AI labs"}]
    assert shown[muted]["watch"] == []
    engine.dispose()


def test_composing_again_replaces_todays_brief_and_keeps_todays_items(tmp_path) -> None:
    """A second run for the same day overwrites the first; today's own items are not 'already briefed'."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine, "Big news", score=90, age_hours=2)
    first = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "one"}, now=NOW)
    second = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "two"}, now=NOW)
    assert first["sections"][0]["stories"][0]["item_id"] == item_id
    assert second["sections"][0]["stories"][0]["item_id"] == item_id and second["opening"] == "two"
    with Session(engine) as session:
        row = session.exec(select(RadarBrief)).one()
        assert loads(row.doc)["opening"] == "two"
    engine.dispose()


def test_refresh_states_reads_the_current_saved_flag(tmp_path) -> None:
    engine = make_engine(tmp_path)
    item_id = add_item(engine, "News", score=85)
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    assert doc["sections"][0]["stories"][0]["state"]["saved"] is False
    with Session(engine) as session:
        session.add(ItemState(item_id=item_id, saved_at=NOW))
        session.commit()
        fresh = refresh_states(session, doc)
    assert fresh["sections"][0]["stories"][0]["state"]["saved"] is True
    assert doc["sections"][0]["stories"][0]["state"]["saved"] is False  # input is not mutated
    engine.dispose()


def test_timezone_helpers() -> None:
    assert brief_tz(SimpleNamespace(radar_timezone="")) is None
    assert brief_tz(SimpleNamespace(radar_timezone="Not/AZone")) is None
    late = SimpleNamespace(radar_timezone="Pacific/Auckland")  # UTC+13 in November
    assert local_today(late, NOW.replace(hour=20)).isoformat() == "2026-11-13"
    assert local_today(SETTINGS, NOW.replace(hour=20)).isoformat() == "2026-11-12"


def test_fallback_opening_variants() -> None:
    top = [{"key": "top", "stories": [{"headline": "Big thing"}]}]
    assert "Big thing" in fallback_opening(top, quiet=False)
    assert "quiet" in fallback_opening([], quiet=True)
    assert "1 top story" in fallback_opening(top, quiet=False)


def test_first_brief_lists_only_recent_from_user_items_capped_at_ten(tmp_path) -> None:
    engine = make_engine(tmp_path)
    for i in range(30):  # a bulk import of old bookmarks
        add_item(engine, f"Old bookmark {i}", score=None, from_user=True, age_hours=24 * 20 + i)
    recent = [add_item(engine, f"Sent {i}", score=None, from_user=True, age_hours=1 + i * 0.1) for i in range(12)]
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    mine = [s["item_id"] for s in stories_of(doc)["from_you"]]
    assert len(mine) == 10
    assert set(mine) <= set(recent)
    assert set(mine) == set(recent[:10])  # the newest ten
    engine.dispose()


def test_later_briefs_list_from_user_items_fetched_since_the_previous_brief(tmp_path) -> None:
    engine = make_engine(tmp_path)
    llm = lambda m, s: {"opening": "x"}  # noqa: E731
    first = add_item(engine, "Sent Monday", score=None, from_user=True, age_hours=30)
    compose_brief(engine, SETTINGS, None, "2026-11-11", llm=llm, now=NOW - timedelta(days=1))
    # An older bookmark that is new to the database only counts if fetched after that brief.
    stale = add_item(engine, "Old bookmark", score=None, from_user=True, age_hours=24 * 9)
    new = add_item(engine, "Sent Tuesday", score=None, from_user=True, age_hours=1)
    doc = compose_brief(engine, SETTINGS, None, "2026-11-12", llm=llm, now=NOW)
    mine = {s["item_id"] for s in stories_of(doc)["from_you"]}
    assert mine == {new}
    assert first not in mine and stale not in mine
    engine.dispose()


def test_from_user_item_outside_the_recency_rule_can_still_appear_as_news(tmp_path) -> None:
    engine = make_engine(tmp_path)
    item_id = add_item(engine, "Assessed old save", score=85, from_user=True, age_hours=3)
    with Session(engine) as session:
        row = session.get(Item, item_id)
        row.fetched_at = row.fetched_at - timedelta(days=30)  # fetched long ago, published today
        session.add(row)
        session.commit()
    doc = compose_brief(engine, SETTINGS, None, llm=lambda m, s: {"opening": "x"}, now=NOW)
    assert "from_you" not in stories_of(doc)
    assert [s["item_id"] for s in stories_of(doc)["top"]] == [item_id]
    engine.dispose()
