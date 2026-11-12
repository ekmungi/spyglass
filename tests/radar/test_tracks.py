"""Tests for the tracks store: create, update, delete, profile topics, queries and recent items."""

import pytest
from sqlmodel import Session

from spyglass_service.radar import tracks
from spyglass_service.radar.models import ItemExtra, dumps
from spyglass_service.radar.profile import get_profile
from spyglass_service.radar.tracks import (
    TrackConflict, TrackError, TrackNotFound, create_track, delete_track, list_tracks,
    merge_queries, recent_item_ids, record_runs, update_track,
)

from .test_brief_seed import add_item, make_engine


@pytest.fixture
def engine(tmp_path):
    """A fresh database."""
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def make(engine, label="Capsule endoscopy AI", **overrides) -> dict:
    """Create a track with sensible defaults."""
    args = {"label": label, "query": '"capsule endoscopy" AI', "section": "health",
            "kind": "topic", **overrides}
    return create_track(engine, **args)


def topics(engine) -> list[str]:
    """Names of the profile's topics."""
    with Session(engine) as session:
        return [t["name"] for t in get_profile(session)["topics"]]


def profile_version(engine) -> int:
    """The stored profile version."""
    with Session(engine) as session:
        return get_profile(session)["version"]


def test_create_stores_the_track_and_adds_the_topic_once(engine) -> None:
    before = profile_version(engine)
    track = make(engine)
    assert track["id"] == 1 and track["active"] is True and track["topic_added"] is True
    assert track["last_run_at"] is None and track["last_new"] == 0
    assert topics(engine).count("Capsule endoscopy AI") == 1
    assert profile_version(engine) == before + 1
    assert list_tracks(engine)[0]["label"] == "Capsule endoscopy AI"


def test_create_does_not_duplicate_an_existing_profile_topic(engine) -> None:
    before = profile_version(engine)
    track = make(engine, label="ai in medical imaging")
    assert track["topic_added"] is False
    assert len(topics(engine)) == 8
    assert profile_version(engine) == before


def test_create_rejects_duplicate_labels_ignoring_case_and_punctuation(engine) -> None:
    make(engine)
    with pytest.raises(TrackConflict):
        make(engine, label="capsule  ENDOSCOPY, AI!")
    assert len(list_tracks(engine)) == 1


@pytest.mark.parametrize("overrides", [
    {"label": "   "}, {"label": "x" * 81}, {"label": "bad\x07label"},
    {"query": ""}, {"query": "q" * 201}, {"query": "line\nbreak"},
    {"section": "nope"}, {"kind": "planet"},
])
def test_create_validates_input(engine, overrides) -> None:
    with pytest.raises(TrackError):
        make(engine, **overrides)
    assert list_tracks(engine) == []


def test_ids_are_not_reused_after_a_delete(engine) -> None:
    first = make(engine, label="One")
    delete_track(engine, first["id"])
    assert make(engine, label="Two")["id"] == 2


def test_delete_removes_only_a_topic_the_track_added(engine) -> None:
    added = make(engine)
    existing = make(engine, label="Open-weights models")
    assert existing["topic_added"] is False
    delete_track(engine, added["id"])
    delete_track(engine, existing["id"])
    names = topics(engine)
    assert "Capsule endoscopy AI" not in names
    assert "Open-weights models" in names
    assert list_tracks(engine) == []


def test_delete_unknown_track_raises(engine) -> None:
    with pytest.raises(TrackNotFound):
        delete_track(engine, 99)


def test_update_pauses_renames_and_moves_the_profile_topic(engine) -> None:
    track = make(engine)
    paused = update_track(engine, track["id"], {"active": False})
    assert paused["active"] is False
    renamed = update_track(engine, track["id"], {"label": "Capsule AI", "section": "industry"})
    assert renamed["label"] == "Capsule AI" and renamed["section"] == "industry"
    with Session(engine) as session:
        topic = [t for t in get_profile(session)["topics"] if t["name"] == "Capsule AI"]
    assert topic == [{"name": "Capsule AI", "section": "industry"}]
    assert "Capsule endoscopy AI" not in topics(engine)


def test_update_errors(engine) -> None:
    make(engine, label="One")
    two = make(engine, label="Two")
    with pytest.raises(TrackConflict):
        update_track(engine, two["id"], {"label": "one"})
    with pytest.raises(TrackError):
        update_track(engine, two["id"], {"section": "nope"})
    with pytest.raises(TrackNotFound):
        update_track(engine, 99, {"active": False})


def test_active_queries_skip_paused_tracks_newest_first(engine) -> None:
    make(engine, label="One", query="q one")
    two = make(engine, label="Two", query="q two")
    make(engine, label="Three", query="q three")
    update_track(engine, two["id"], {"active": False})
    assert tracks.active_queries(engine) == ["q three", "q one"]


def test_merge_queries_puts_tracks_first_dedupes_and_caps() -> None:
    merged = merge_queries(["B", "a"], ["A", "c", "b"])
    assert merged == ["B", "a", "c"]
    many = merge_queries([f"t{i}" for i in range(30)], [f"p{i}" for i in range(30)])
    assert len(many) == 40 and many[0] == "t0" and many[29] == "t29" and many[30] == "p0"


def test_record_runs_updates_only_the_tracks_that_ran(engine) -> None:
    one = make(engine, label="One", query="q one")
    two = make(engine, label="Two", query="q two")
    record_runs(engine, {"q one"}, {"q one": 3})
    by_id = {t["id"]: t for t in list_tracks(engine)}
    assert by_id[one["id"]]["last_new"] == 3 and by_id[one["id"]]["last_run_at"]
    assert by_id[two["id"]]["last_run_at"] is None


def test_recent_item_ids_match_the_stored_query_newest_first(engine) -> None:
    old = add_item(engine, "Old story", age_hours=30)
    new = add_item(engine, "New story", age_hours=2)
    other = add_item(engine, "Other story", age_hours=1)
    with Session(engine) as session:
        for item_id, query in ((old, "q"), (new, "q"), (other, "different")):
            session.add(ItemExtra(item_id=item_id, data=dumps({"query": query})))
        session.commit()
        assert recent_item_ids(session, "q", 3) == [new, old]
        assert recent_item_ids(session, "q", 1) == [new]
        assert recent_item_ids(session, "none") == []


def test_run_track_now_counts_new_items_and_survives_a_failing_search(engine) -> None:
    from spyglass_service.radar.sources import news_search

    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>q</title><item>'
        "<title>A story - Wire</title><link>https://news.google.com/rss/articles/ZZ1?oc=5</link>"
        "<pubDate>Thu, 12 Nov 2026 08:00:00 GMT</pubDate><source url=\"https://w.example\">Wire"
        "</source></item></channel></rss>"
    ).encode()
    track = make(engine)
    settings = object()
    new = tracks.run_track_now(engine, settings, track, fetch=lambda url: feed,
                               decode=lambda links: [None] * len(links))
    assert new == 1
    assert list_tracks(engine)[0]["last_new"] == 1
    with Session(engine) as session:
        assert len(recent_item_ids(session, track["query"])) == 1

    def boom(url: str) -> bytes:
        raise OSError("down")

    assert tracks.run_track_now(engine, settings, track, fetch=boom) == 0
    assert news_search.SOURCE == "news"
