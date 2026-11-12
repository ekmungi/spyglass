"""Tests for the brief endpoints, on a small app that mounts only the brief router."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.radar.api.briefs import router
from spyglass_service.radar.brief.compose import compose_brief
from spyglass_service.radar.models import ItemState, RadarBrief

from .test_brief_seed import NOW, add_item, make_engine

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)


@pytest.fixture
def env(tmp_path):
    """(client, engine) for an app with only the brief router."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    app.state.settings = SETTINGS
    app.state.service_state = SimpleNamespace(ensure_index=lambda: None)
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def test_today_with_no_brief(env) -> None:
    client, _ = env
    body = client.get("/today").json()
    assert body["brief"] is None and body["days"] == []
    assert body["status"]["has_today"] is False


def test_today_returns_latest_brief_days_and_sets_opened_at(env) -> None:
    client, engine = env
    add_item(engine, "News", score=85)
    compose_brief(engine, SETTINGS, None, "2026-11-10", llm=lambda m, s: {"opening": "x"}, now=NOW)
    compose_brief(engine, SETTINGS, None, "2026-11-12", llm=lambda m, s: {"opening": "y"}, now=NOW)
    body = client.get("/today").json()
    assert body["days"] == ["2026-11-12", "2026-11-10"]
    assert body["brief"]["day"] == "2026-11-12"
    assert body["status"]["latest_day"] == "2026-11-12"
    with Session(engine) as session:
        latest = session.exec(select(RadarBrief).where(RadarBrief.day == "2026-11-12")).one()
        assert latest.opened_at is not None


def test_states_are_refreshed_when_read(env) -> None:
    client, engine = env
    item_id = add_item(engine, "News", score=85)
    compose_brief(engine, SETTINGS, None, "2026-11-12", llm=lambda m, s: {"opening": "x"}, now=NOW)
    with Session(engine) as session:
        session.add(ItemState(item_id=item_id, saved_at=datetime.now(UTC)))
        session.commit()
    story = client.get("/briefs/2026-11-12").json()["sections"][0]["stories"][0]
    assert story["state"]["saved"] is True


def test_get_brief_404_and_bad_day(env) -> None:
    client, _ = env
    assert client.get("/briefs/2026-01-01").status_code == 404
    assert client.get("/briefs/not-a-day").status_code == 422


def test_generate_composes_and_returns_the_doc(env) -> None:
    client, engine = env
    add_item(engine, "News", score=85, age_hours=0.1)
    resp = client.post("/briefs/generate", json={"day": None})
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["opening"] and "sections" in doc
    with Session(engine) as session:
        assert session.exec(select(RadarBrief)).first() is not None


def test_generate_rejects_a_malformed_or_impossible_day(env) -> None:
    client, _ = env
    assert client.post("/briefs/generate", json={"day": "tomorrow"}).status_code == 422
    assert client.post("/briefs/generate", json={"day": "2026-02-31"}).status_code == 422


def _add_briefs(engine, days_ago_opened: dict[int, bool]) -> dict[int, str]:
    """Store a bare brief for each "days ago" key (True = already opened); return the day texts."""
    today = datetime.now(UTC).date()
    days: dict[int, str] = {}
    with Session(engine) as session:
        for ago, opened in days_ago_opened.items():
            day = (today - timedelta(days=ago)).isoformat()
            days[ago] = day
            session.add(RadarBrief(
                day=day, doc=json.dumps({"day": day, "generated_at": "2026-01-01T00:00:00",
                                         "sections": []}),
                opened_at=datetime.now(UTC) if opened else None))
        session.commit()
    return days


def test_today_lists_unopened_briefs_of_the_last_week_newest_first(env) -> None:
    client, engine = env
    days = _add_briefs(engine, {0: False, 1: False, 2: True, 3: False, 7: False, 8: False})
    body = client.get("/today").json()
    # Today's own brief is excluded, an opened one is excluded, and 8 days back is too old.
    assert body["unopened_days"] == [days[1], days[3], days[7]]
    assert body["brief"]["day"] == days[0]


def test_unopened_days_is_empty_when_everything_was_read_or_nothing_exists(env) -> None:
    client, engine = env
    assert client.get("/today").json()["unopened_days"] == []
    _add_briefs(engine, {0: False, 1: True})
    assert client.get("/today").json()["unopened_days"] == []


def test_the_latest_brief_counts_as_opened_even_when_it_is_not_today(env) -> None:
    client, engine = env
    days = _add_briefs(engine, {1: False, 2: False})
    assert client.get("/today").json()["unopened_days"] == [days[2]]


def test_opening_a_day_marks_it_opened_and_drops_it_from_the_list(env) -> None:
    client, engine = env
    days = _add_briefs(engine, {0: True, 1: False, 2: False})
    assert client.get("/today").json()["unopened_days"] == [days[1], days[2]]
    assert client.get(f"/briefs/{days[1]}").status_code == 200
    with Session(engine) as session:
        row = session.exec(select(RadarBrief).where(RadarBrief.day == days[1])).one()
        assert row.opened_at is not None
    assert client.get("/today").json()["unopened_days"] == [days[2]]


def test_opening_a_day_keeps_the_first_opened_time(env) -> None:
    client, engine = env
    days = _add_briefs(engine, {0: True, 1: False})
    client.get(f"/briefs/{days[1]}")
    with Session(engine) as session:
        first = session.exec(select(RadarBrief).where(RadarBrief.day == days[1])).one().opened_at
    client.get(f"/briefs/{days[1]}")
    with Session(engine) as session:
        assert session.exec(select(RadarBrief).where(
            RadarBrief.day == days[1])).one().opened_at == first


def test_story_section_labels_follow_the_profile_after_a_rename(env) -> None:
    from spyglass_service.radar.models import RadarDoc, dumps
    from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE, PROFILE_KEY

    client, engine = env
    add_item(engine, "News", score=85, section="health")
    compose_brief(engine, SETTINGS, None, "2026-11-12", llm=lambda m, s: {"opening": "x"}, now=NOW)

    def labels() -> set[str]:
        doc = client.get("/briefs/2026-11-12").json()
        return {st["section_label"] for sec in doc["sections"] for st in sec["stories"]}

    assert labels() == {"Healthcare AI & medtech"}
    renamed = {**DEFAULT_PROFILE, "sections": [
        {**s, "label": "Clinical AI" if s["key"] == "health" else s["label"]}
        for s in DEFAULT_PROFILE["sections"]]}
    with Session(engine) as session:
        session.add(RadarDoc(key=PROFILE_KEY, body=dumps(renamed)))
        session.commit()
    assert labels() == {"Clinical AI"}
