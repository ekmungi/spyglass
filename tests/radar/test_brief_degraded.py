"""Regression tests for the brief: an outage is never a quiet day, regenerating a past day
leaves the next brief alone, future days are refused, and two composes never collide."""

import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.models import Feed, Item
from spyglass_service.radar.api.briefs import router
from spyglass_service.radar.assess import store_assessment
from spyglass_service.radar.brief import compose as compose_module
from spyglass_service.radar.brief.compose import compose_brief
from spyglass_service.radar.models import RadarBrief, dumps, loads

from .test_brief_seed import NOW, add_item, make_engine

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)


def LLM(_messages, _schema):  # noqa: N802 -- a constant-like fake
    """A writer model that always answers."""
    return {"opening": "x"}


def _ids(doc: dict) -> set[int]:
    """Lead item ids shown anywhere in a brief document."""
    return {st["item_id"] for sec in doc["sections"] for st in sec["stories"]}


@pytest.fixture
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def test_a_day_the_model_was_down_is_degraded_not_quiet(engine) -> None:
    """40 items collected and none judged: the brief says so instead of calling the day quiet."""
    for i in range(40):
        add_item(engine, f"Unjudged {i}", score=None, age_hours=1 + i * 0.2)
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert doc["unjudged"] == 40 and doc["degraded"] is True
    assert doc["quiet"] is False and doc["filtered_out"] == 0
    assert "40 items" in doc["notice"] and "incomplete" in doc["notice"]


def test_filtered_out_counts_only_judged_items_that_were_left_out(engine) -> None:
    """filtered_out = collected minus shown minus unjudged."""
    for i in range(3):
        add_item(engine, f"Kept {i}", score=85)
    for i in range(4):
        add_item(engine, f"Dropped {i}", score=5, tier="out")
    for i in range(5):
        add_item(engine, f"Not judged {i}", score=None)
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert doc["collected"] == 12 and doc["unjudged"] == 5 and doc["filtered_out"] == 4


def test_a_normal_day_is_not_degraded(engine) -> None:
    """Everything judged: the new fields say so and there is no notice."""
    add_item(engine, "Story", score=80)
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert doc["unjudged"] == 0 and doc["degraded"] is False and doc["notice"] is None


def test_failed_triages_count_as_unjudged_and_are_not_news(engine) -> None:
    """An item whose triage failed is unjudged, never a news candidate with score 0."""
    item_id = add_item(engine, "Failed triage", score=None)
    store_assessment(engine, item_id, {"stage": "triage_failed", "score": 0, "tier": "unjudged",
                                       "error": "triage failed"})
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert item_id not in _ids(doc) and doc["unjudged"] == 1


def test_items_of_switched_off_feeds_are_not_counted_as_unjudged(engine) -> None:
    """The pipeline skips switched-off feeds on purpose; that is not an outage."""
    item_id = add_item(engine, "From a feed that is off", score=None)
    with Session(engine) as session:
        session.add(Feed(feed_url="https://off.test/feed", name="Off", kind="rss", enabled=False,
                         added_via="manual"))
        item = session.get(Item, item_id)
        item.feed_url = "https://off.test/feed"
        session.add(item)
        session.commit()
    assert compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)["unjudged"] == 0


def test_regenerating_a_past_day_does_not_drop_a_link_from_the_next_brief(engine) -> None:
    """Yesterday's brief regenerated this morning must not move the next "From you" window."""
    yesterday = (NOW - timedelta(days=1)).replace(hour=6, minute=30)
    compose_brief(engine, SETTINGS, None, llm=LLM, now=yesterday)
    mine = add_item(engine, "My link", score=None, from_user=True, age_hours=9)  # 03:00 today
    compose_brief(engine, SETTINGS, None, day=yesterday.date(), llm=LLM,
                  now=NOW.replace(hour=5))
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert mine in {st["item_id"] for sec in doc["sections"] if sec["key"] == "from_you"
                    for st in sec["stories"]}
    with Session(engine) as session:
        row = session.exec(select(RadarBrief).where(RadarBrief.day == "2026-11-11")).one()
    assert row.created_at == yesterday.replace(tzinfo=None)
    assert row.regenerated_at == NOW.replace(hour=5, tzinfo=None)


def test_a_from_you_item_already_in_an_earlier_brief_is_not_repeated(engine) -> None:
    """From you means sent in and not shown in any earlier brief."""
    mine = add_item(engine, "Sent yesterday", score=None, from_user=True, age_hours=20)
    first = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW - timedelta(hours=2))
    assert mine in _ids(first)
    tomorrow = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW + timedelta(days=1))
    assert mine not in _ids(tomorrow)


def test_composing_a_future_day_is_refused(engine) -> None:
    """A day after the local today cannot be composed."""
    with pytest.raises(ValueError):
        compose_brief(engine, SETTINGS, None, day="2099-01-01", llm=LLM, now=NOW)


@pytest.fixture
def client(engine):
    """A test client for an app with only the brief router."""
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    app.state.settings = SETTINGS
    app.state.service_state = SimpleNamespace(ensure_index=lambda: None)
    with TestClient(app) as test_client:
        yield test_client


def test_generate_refuses_future_and_impossible_days(client) -> None:
    """422 for a future day and for a date that does not exist."""
    assert client.post("/briefs/generate", json={"day": "2099-01-01"}).status_code == 422
    assert client.post("/briefs/generate", json={"day": "2026-02-31"}).status_code == 422


def test_today_ignores_a_stored_future_brief(client, engine) -> None:
    """A future brief stored by an older version never becomes the latest brief."""
    compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    with Session(engine) as session:
        session.add(RadarBrief(day="2099-01-01", doc=dumps({"day": "2099-01-01", "sections": []})))
        session.commit()
    body = client.get("/today").json()
    assert body["brief"]["day"] != "2099-01-01" and "2099-01-01" not in body["days"]


def test_two_composes_at_once_do_not_collide(engine, monkeypatch) -> None:
    """A scheduled compose and a "generate now" for the same day both succeed."""
    add_item(engine, "Story", score=80)
    real = compose_module.build_document
    inside = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow_build(*args, **kwargs):
        with lock:
            inside["now"] += 1
            inside["max"] = max(inside["max"], inside["now"])
        threading.Event().wait(0.3)
        with lock:
            inside["now"] -= 1
        return real(*args, **kwargs)

    monkeypatch.setattr(compose_module, "build_document", slow_build)
    errors: list[BaseException] = []

    def run():
        try:
            compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
        except BaseException as exc:  # noqa: BLE001 -- collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == [] and inside["max"] == 1
    with Session(engine) as session:
        assert len(session.exec(select(RadarBrief)).all()) == 1


def test_a_non_numeric_upvote_count_does_not_break_the_brief(engine) -> None:
    """Community vote counts arrive as text from some sources; a bad one is read as 0."""
    paper = add_item(engine, "A paper", score=80, kind="paper")
    with Session(engine) as session:
        from spyglass_service.radar.models import ItemExtra

        session.add(ItemExtra(item_id=paper, data=dumps({"upvotes": "1.2k"})))
        session.commit()
    doc = compose_brief(engine, SETTINGS, None, llm=LLM, now=NOW)
    assert paper in _ids(doc) and loads(dumps(doc))["day"] == "2026-11-12"


def test_one_stray_unjudged_item_does_not_make_a_large_day_incomplete() -> None:
    """A single failure among hundreds is not an outage; a meaningful share is."""
    from spyglass_service.radar.brief.document import is_degraded

    assert not is_degraded(0, 500)
    assert not is_degraded(1, 500)
    assert is_degraded(10, 5000)   # at least ten items
    assert is_degraded(3, 40)      # a meaningful share of a small day
    assert not is_degraded(2, 0)   # nothing collected: no share to speak of
