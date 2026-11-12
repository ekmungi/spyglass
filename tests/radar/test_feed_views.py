"""Tests for the Feed's two saved views: `missed=true` and `watch_group=<name>` on GET /feed."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import feed_views
from spyglass_service.radar.api import items as items_api
from spyglass_service.radar.filing_queue import FilingRow
from spyglass_service.radar.models import (
    Assessment, ItemEntity, ItemExtra, ItemState, Signal, WatchEntity, dumps, utcnow,
)
from spyglass_service.radar.watch import registry

NOW = datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def env(tmp_path):
    """A small app with only the items router, and a TestClient on it."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    app = FastAPI()
    app.include_router(items_api.router, prefix="/api/radar")
    app.state.engine = engine
    app.state.settings = Settings(data_dir=tmp_path)
    yield engine, TestClient(app)
    engine.dispose()


def add_item(engine, n: int, *, tier: str | None = "notable", age_days: float = 1, score: int = 50,
             fetched_age_days: float | None = None, section: str = "models") -> int:
    """Insert an item published `age_days` ago, with an assessment unless `tier` is None."""
    when = NOW - timedelta(days=age_days)
    fetched = NOW - timedelta(days=age_days if fetched_age_days is None else fetched_age_days)
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"e{n}", title=f"Item {n}", url=f"https://x.example/{n}",
                    published_at=when, fetched_at=fetched)
        session.add(item)
        session.commit()
        if tier is not None:
            session.add(Assessment(item_id=item.id, tier=tier, section=section, kind="news", score=score,
                                   key_points=dumps([]), entities=dumps([])))
            session.commit()
        return item.id


def ids(response) -> list[int]:
    """The item ids of a feed response, in order."""
    return [i["id"] for i in response.json()["items"]]


def set_state(engine, item_id: int, **fields) -> None:
    """Create the item's reader-state row with the given fields."""
    with Session(engine) as session:
        session.add(ItemState(item_id=item_id, **fields))
        session.commit()


# --- missed ----------------------------------------------------------------------------------


def test_missed_lists_unseen_top_and_notable_items_of_the_last_seven_days(env) -> None:
    engine, client = env
    top = add_item(engine, 1, tier="top", score=90)
    notable = add_item(engine, 2, tier="notable", score=60)
    add_item(engine, 3, tier="skim")
    add_item(engine, 4, tier="out")
    add_item(engine, 5, tier=None)
    response = client.get("/api/radar/feed?missed=true")
    assert response.status_code == 200
    assert ids(response) == [top, notable]
    assert response.json()["total"] == 2


def test_missed_orders_by_score_then_newest_first(env) -> None:
    engine, client = env
    low_new = add_item(engine, 1, tier="notable", age_days=1, score=55)
    high_old = add_item(engine, 2, tier="top", age_days=5, score=95)
    tie_new = add_item(engine, 3, tier="notable", age_days=2, score=70)
    tie_old = add_item(engine, 4, tier="notable", age_days=4, score=70)
    assert ids(client.get("/api/radar/feed?missed=true")) == [high_old, tie_new, tie_old, low_new]


def test_missed_seven_day_edge_uses_the_date_the_feed_is_ordered_by(env) -> None:
    engine, client = env
    inside = add_item(engine, 1, age_days=6.9)
    add_item(engine, 2, age_days=7.1)
    # Published long ago but fetched yesterday: the feed orders on the publish date, so it is out.
    add_item(engine, 3, age_days=30, fetched_age_days=1)
    assert ids(client.get("/api/radar/feed?missed=true")) == [inside]


def test_missed_condition_cutoff_is_exact_to_the_second(env) -> None:
    engine, _ = env
    now = datetime(2026, 11, 12, 12, 0, 0)
    sort_key = Item.published_at
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="a", title="A", url="https://x.example/a",
                         published_at=now - timedelta(days=7), fetched_at=now))
        session.add(Item(source="rss", external_id="b", title="B", url="https://x.example/b",
                         published_at=now - timedelta(days=7, seconds=1), fetched_at=now))
        session.commit()
        picked = session.exec(select(Item).where(feed_views.recent_condition(sort_key, now))).all()
    assert [row.external_id for row in picked] == ["a"]


def test_missed_drops_what_the_reader_has_opened_saved_filed_queued_or_dismissed(env) -> None:
    engine, client = env
    kept = add_item(engine, 1)
    opened = add_item(engine, 2)
    saved = add_item(engine, 3)
    saved_then_removed = add_item(engine, 4)
    filed = add_item(engine, 5)
    queued = add_item(engine, 6)
    hidden = add_item(engine, 7)
    sent_in = add_item(engine, 8)
    opened_signal_only = add_item(engine, 9)
    set_state(engine, kept)  # a state row with nothing done does not hide the item
    set_state(engine, opened, opened_at=utcnow(), open_count=1)
    set_state(engine, saved, saved_at=utcnow())
    set_state(engine, saved_then_removed, saved_at=None)
    set_state(engine, hidden, hidden=True)
    set_state(engine, sent_in, from_user=True)
    with Session(engine) as session:
        session.add(Signal(item_id=saved_then_removed, kind="save"))
        session.add(Signal(item_id=saved_then_removed, kind="unsave"))
        session.add(Signal(item_id=opened_signal_only, kind="open"))
        session.add(Signal(item_id=None, kind="open"))  # a signal with no item must not hide anything
        session.add(ItemExtra(item_id=filed, data=dumps({"filed": {"path": "Inbox/N.md", "project": "P"}})))
        session.add(FilingRow(item_id=queued))
        session.commit()
    assert ids(client.get("/api/radar/feed?missed=true")) == [kept]


def test_missed_is_one_page_with_no_cursor_and_ignores_before(env) -> None:
    engine, client = env
    made = [add_item(engine, n, score=90 - n, age_days=0.5 + n / 10) for n in range(1, 6)]
    # A date cursor cannot page a list ordered by score, so `before` is ignored.
    response = client.get("/api/radar/feed?missed=true&before=2020-01-01T00:00:00")
    assert ids(response) == made and response.json()["next_before"] is None
    # When more match than `limit`, the page is cut by score and still has no next page.
    short = client.get("/api/radar/feed?missed=true&limit=2")
    assert ids(short) == made[:2] and short.json()["next_before"] is None and short.json()["total"] == 5


def test_missed_combines_with_a_section_filter(env) -> None:
    engine, client = env
    models = add_item(engine, 1, section="models")
    add_item(engine, 2, section="health")
    assert ids(client.get("/api/radar/feed?missed=true&section=models")) == [models]


def test_missed_false_changes_nothing(env) -> None:
    engine, client = env
    a = add_item(engine, 1, tier="skim", age_days=1)
    b = add_item(engine, 2, tier="top", age_days=2)
    assert ids(client.get("/api/radar/feed?missed=false")) == [a, b]


# --- watch group -----------------------------------------------------------------------------


def add_entity(engine, name: str, category: str, status: str = "active") -> int:
    """Insert a watched entity and return its id."""
    with Session(engine) as session:
        entity = WatchEntity(name=name, category=category, status=status)
        session.add(entity)
        session.commit()
        return entity.id


def link(engine, item_id: int, entity_id: int) -> None:
    """Link an item to an entity."""
    with Session(engine) as session:
        session.add(ItemEntity(item_id=item_id, entity_id=entity_id))
        session.commit()


def group_count(engine, name: str) -> int:
    """The week count the Watch page shows for a group."""
    with Session(engine) as session:
        groups = registry.grouped(session)["categories"]
    return next(g["week_count"] for g in groups if g["name"] == name)


def test_watch_group_rows_and_the_week_count_on_the_watch_page_agree(env) -> None:
    engine, client = env
    lab_a = add_entity(engine, "Lab A", "AI labs")
    lab_b = add_entity(engine, "Lab B", "AI labs")
    muted = add_entity(engine, "Lab C", "AI labs", status="muted")
    suggested = add_entity(engine, "Lab D", "AI labs", status="suggested")
    other = add_entity(engine, "Firm", "Endoscopy AI")
    both = add_item(engine, 1, age_days=1)
    only_a = add_item(engine, 2, age_days=2)
    only_muted = add_item(engine, 3, age_days=3)
    unjudged_old = add_item(engine, 4, tier=None, age_days=6)  # older than the default feed shows
    skim = add_item(engine, 5, tier="skim", age_days=1)
    out = add_item(engine, 6, tier="out", age_days=1)
    too_old = add_item(engine, 7, age_days=1, fetched_age_days=8)
    only_suggested = add_item(engine, 8, age_days=1)
    elsewhere = add_item(engine, 9, age_days=1)
    for item_id, entity_id in [(both, lab_a), (both, lab_b), (only_a, lab_a), (only_muted, muted), (unjudged_old, lab_b),
                               (skim, lab_a), (out, lab_a), (too_old, lab_a), (only_suggested, suggested),
                               (elsewhere, other)]:
        link(engine, item_id, entity_id)
    response = client.get("/api/radar/feed?watch_group=AI%20labs")
    assert response.status_code == 200
    rows = ids(response)
    assert set(rows) == {both, only_a, only_muted, unjudged_old, skim}
    assert len(rows) == response.json()["total"] == group_count(engine, "AI labs") == 5
    # Newest first (equal times by id, newest id first), like every other view of the Feed.
    assert rows == [skim, both, only_a, only_muted, unjudged_old]
    assert ids(client.get("/api/radar/feed?watch_group=Endoscopy%20AI")) == [elsewhere]


def test_watch_group_without_a_category_is_called_other(env) -> None:
    engine, client = env
    entity = add_entity(engine, "Loner", "")
    item = add_item(engine, 1)
    link(engine, item, entity)
    assert ids(client.get("/api/radar/feed?watch_group=Other")) == [item]
    assert group_count(engine, "Other") == 1


def test_an_unknown_watch_group_gives_an_empty_list_not_an_error(env) -> None:
    engine, client = env
    add_item(engine, 1)
    response = client.get("/api/radar/feed?watch_group=Nobody")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_before": None, "total": 0}


def test_watch_group_pages_with_the_cursor(env) -> None:
    engine, client = env
    entity = add_entity(engine, "Lab A", "AI labs")
    made = [add_item(engine, n, age_days=n) for n in range(1, 5)]
    for item_id in made:
        link(engine, item_id, entity)
    first = client.get("/api/radar/feed?watch_group=AI%20labs&limit=2").json()
    assert [i["id"] for i in first["items"]] == made[:2] and first["next_before"]
    second = client.get(f"/api/radar/feed?watch_group=AI%20labs&limit=2&before={first['next_before']}").json()
    assert [i["id"] for i in second["items"]] == made[2:]


def test_watch_group_and_missed_together_narrow_the_list(env) -> None:
    engine, client = env
    entity = add_entity(engine, "Lab A", "AI labs")
    seen = add_item(engine, 1)
    unseen = add_item(engine, 2)
    skim = add_item(engine, 3, tier="skim")
    for item_id in (seen, unseen, skim):
        link(engine, item_id, entity)
    set_state(engine, seen, opened_at=utcnow())
    assert ids(client.get("/api/radar/feed?watch_group=AI%20labs&missed=true")) == [unseen]


def test_group_item_ids_is_empty_for_a_group_with_no_followed_names(env) -> None:
    engine, _ = env
    add_entity(engine, "Only suggested", "Ghosts", status="suggested")
    with Session(engine) as session:
        assert feed_views.watch_group_item_ids(session, "Ghosts") == set()
        assert feed_views.watch_group_item_ids(session, "") == set()
