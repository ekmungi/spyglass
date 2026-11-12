"""Tests that the news collector runs the active tracks' queries each cycle."""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import ItemExtra, loads
from spyglass_service.radar.sources.news_search import collect_news, topic_queries
from spyglass_service.radar.tracks import create_track, list_tracks, update_track

from .test_brief_seed import make_engine
from .test_sources_support import make_settings

ONE_RESULT = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>q</title><item>'
    "<title>Story - Wire</title><link>https://news.google.com/rss/articles/TRK1?oc=5</link>"
    "<pubDate>Thu, 12 Nov 2026 08:00:00 GMT</pubDate><source url=\"https://w.example\">Wire"
    "</source></item></channel></rss>"
).encode()
EMPTY = b'<?xml version="1.0"?><rss version="2.0"><channel><title>q</title></channel></rss>'


@pytest.fixture
def engine(tmp_path):
    """A fresh database."""
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def recording_fetch(body: bytes = EMPTY):
    """A fetch function that records the search text of every request."""
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(parse_qs(urlparse(url).query)["q"][0].removesuffix(" when:2d"))
        return body

    return seen, fetch


def track(engine, label: str, query: str) -> dict:
    """Create a health-section topic track."""
    return create_track(engine, label=label, query=query, section="health", kind="topic")


def test_cycle_runs_active_track_queries_before_the_topic_queries(engine) -> None:
    track(engine, "Capsule AI", '"capsule endoscopy" AI')
    seen, fetch = recording_fetch()
    collect_news(engine, make_settings(), fetch=fetch, pause=0)
    assert seen[0] == '"capsule endoscopy" AI'
    # The track's own label became a profile topic, so it adds a query of its own as well.
    assert seen.count('"capsule endoscopy" AI') == 1
    assert "AI regulation law policy" in seen


def test_cycle_skips_paused_tracks(engine) -> None:
    made = track(engine, "Capsule AI", "paused query")
    update_track(engine, made["id"], {"active": False})
    seen, fetch = recording_fetch()
    collect_news(engine, make_settings(), fetch=fetch, pause=0)
    assert "paused query" not in seen


def test_cycle_caps_the_total_at_forty_with_tracks_first(engine) -> None:
    for number in range(45):
        track(engine, f"Subject {number}", f"query {number}")
    seen, fetch = recording_fetch()
    collect_news(engine, make_settings(), fetch=fetch, pause=0)
    assert len(seen) == 40
    assert seen[0] == "query 44" and "query 5" in seen
    assert not set(topic_queries()) & set(seen)


def test_cycle_records_last_run_and_new_count_per_track(engine) -> None:
    track(engine, "Capsule AI", "capsule query")
    track(engine, "Idle", "idle query")
    seen, fetch = recording_fetch()
    # Only the capsule query returns a result.
    def routed(url: str) -> bytes:
        body = ONE_RESULT if "capsule" in url else EMPTY
        seen.append(url)
        return body

    collect_news(engine, make_settings(), fetch=routed, decode=lambda ls: [None] * len(ls),
                 pause=0)
    by_label = {t["label"]: t for t in list_tracks(engine)}
    assert by_label["Capsule AI"]["last_new"] == 1 and by_label["Capsule AI"]["last_run_at"]
    assert by_label["Idle"]["last_new"] == 0 and by_label["Idle"]["last_run_at"]
    with Session(engine) as session:
        queries = [loads(e.data).get("query") for e in session.exec(select(ItemExtra)).all()]
    assert queries == ["capsule query"]


def test_an_explicit_query_list_is_left_alone(engine) -> None:
    track(engine, "Capsule AI", "capsule query")
    seen, fetch = recording_fetch()
    collect_news(engine, make_settings(), fetch=fetch, queries=["only this"], pause=0)
    assert seen == ["only this"]
    assert list_tracks(engine)[0]["last_run_at"] is None


def test_a_failing_track_query_does_not_get_a_run_time(engine) -> None:
    track(engine, "Broken", "bad query")
    track(engine, "Fine", "good query")

    def flaky(url: str) -> bytes:
        if "bad" in url:
            raise OSError("down")
        return EMPTY

    collect_news(engine, make_settings(), fetch=flaky, pause=0)
    by_label = {t["label"]: t for t in list_tracks(engine)}
    assert by_label["Broken"]["last_run_at"] is None
    assert by_label["Fine"]["last_run_at"] is not None
