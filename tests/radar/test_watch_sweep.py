"""Tests for the watch sweep: collecting, linking and suggesting."""

from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.ingest import store_items
from spyglass_service.radar.models import ItemEntity, WatchEntity
from spyglass_service.radar.watch import registry, sweep
from spyglass_service.radar.watch._news_fallback import search_news

from .test_brief_seed import NOW_NAIVE, add_item, make_engine

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Robot cleared by FDA - STAT</title><link>https://news.example/1</link>
<guid>g1</guid><pubDate>Wed, 11 Nov 2026 10:00:00 GMT</pubDate><source url="https://stat.example">STAT</source>
<description>&lt;a href="x"&gt;Robot cleared&lt;/a&gt;</description></item>
<item><title></title><link>https://news.example/2</link></item></channel></rss>"""


def item(ext: str, title: str = "t") -> CollectedItem:
    """A collected news item."""
    return CollectedItem(source="news", external_id=ext, title=title, url=f"https://n.example/{ext}")


def seed_entities(engine, *names: str) -> list[int]:
    """Create active entities; return their ids."""
    with Session(engine) as s:
        return [registry.create_entity(s, n).id for n in names]


def test_fallback_search_parses_google_news_rss() -> None:
    urls = []

    def fetch(url: str) -> str:
        urls.append(url)
        return RSS

    got = search_news("robot", days=3, fetch=fetch)
    assert "when%3A3d" in urls[0]
    assert len(got) == 1
    assert got[0].title == "Robot cleared by FDA" and got[0].origin == "STAT"
    assert got[0].external_id == "g1" and got[0].published_at.year == 2026
    assert got[0].summary == "Robot cleared"


def test_watch_collect_tags_merges_duplicates_and_skips_failures(tmp_path) -> None:
    engine = make_engine(tmp_path)
    a, b, c = seed_entities(engine, "Alpha", "Beta", "Gamma")
    queries = []
    sleeps = []

    def search(query: str, days: int = 3):
        queries.append(query)
        if query == '"Gamma"':
            raise RuntimeError("down")
        return [item("shared"), item(f"only-{query}")]

    out = sweep.watch_collect(engine, None, search=search, sleep=sleeps.append, pause=1.0)
    assert len(queries) == 3 and len(sleeps) == 2  # throttled between searches
    by_ext = {i.external_id: i for i in out}
    assert by_ext["shared"].source == "watch"
    assert by_ext["shared"].source_tags == [f"watch:{a}", f"watch:{b}"]
    assert by_ext['only-"Alpha"'].source_tags == [f"watch:{a}"]
    assert f"watch:{c}" not in {t for i in out for t in i.source_tags}
    engine.dispose()


def test_collect_store_link_roundtrip_and_relink_of_stored_items(tmp_path) -> None:
    engine = make_engine(tmp_path)
    a, b = seed_entities(engine, "Alpha", "Beta")
    first = sweep.watch_collect(engine, None, search=lambda q, days=3: [item("x")] if "Alpha" in q else [],
                                sleep=lambda s: None)
    assert store_items(engine, first) == 1
    assert sweep.link_watch_items(engine) == 1
    assert sweep.link_watch_items(engine) == 0  # idempotent
    # Next day another entity finds the same, already stored item.
    sweep.watch_collect(engine, None, search=lambda q, days=3: [item("x")] if "Beta" in q else [],
                        sleep=lambda s: None)
    with Session(engine) as s:
        links = s.exec(select(ItemEntity.entity_id)).all()
        assert sorted(links) == [a, b]
        assert s.get(WatchEntity, a).last_hit_at is not None
    engine.dispose()


def test_watch_collect_ignores_suggested_entities_and_handles_no_entities(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        registry.create_entity(s, "Maybe", status="suggested")
    called = []
    assert sweep.watch_collect(engine, None, search=lambda q, days=3: called.append(q) or []) == []
    assert called == []
    engine.dispose()


def test_link_mentions_matches_whole_names_and_aliases(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        eid = registry.create_entity(s, "Intuitive Surgical", aliases=["da Vinci maker"]).id
        registry.create_entity(s, "Off", status="muted")
    hit = add_item(engine, "a", entities=["intuitive surgical!", "FDA"])
    alias = add_item(engine, "b", entities=["Da Vinci Maker"])
    add_item(engine, "c", entities=["Intuitive"])  # partial name: no match
    add_item(engine, "d", entities=["Off"])  # muted entities are not matched
    add_item(engine, "e", entities=None)
    assert sweep.link_mentions(engine) == 2
    assert sweep.link_mentions(engine) == 0
    with Session(engine) as s:
        rows = s.exec(select(ItemEntity)).all()
        assert {(r.item_id, r.entity_id, r.via) for r in rows} == {(hit, eid, "mention"), (alias, eid, "mention")}
    engine.dispose()


def test_link_mentions_without_entities_is_zero(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "a", entities=["X"])
    assert sweep.link_mentions(engine) == 0
    engine.dispose()


def test_suggest_from_mentions_threshold_register_and_window(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        registry.create_entity(s, "Known Co")
    for i in range(3):
        add_item(engine, f"n{i}", entities=["Newco", "Known Co"])
    add_item(engine, "rare1", entities=["Rareco"])
    add_item(engine, "rare2", entities=["Rareco"])
    for i in range(3):
        add_item(engine, f"old{i}", entities=["Oldco"], age_hours=24 * 40)
    for i in range(3):
        add_item(engine, f"out{i}", entities=["Outco"], score=3, tier="out")
    assert sweep.suggest_from_mentions(engine, now=NOW_NAIVE) == 1
    assert sweep.suggest_from_mentions(engine, now=NOW_NAIVE) == 0
    with Session(engine) as s:
        new = s.exec(select(WatchEntity).where(WatchEntity.name == "Newco")).one()
        assert new.status == "suggested" and new.added_via == "discovered"
        assert new.why == "named in 3 relevant items"
    assert sweep.suggest_from_mentions(engine, min_count=2, now=NOW_NAIVE) == 1  # Rareco now qualifies
    engine.dispose()
