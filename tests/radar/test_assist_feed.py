# ruff: noqa: F811
"""Tests for the assistant's conversation about the whole feed: context, presets, threads, API."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.radar import privacy
from spyglass_service.radar.api import assist as assist_api
from spyglass_service.radar.assist import context, feed_context, threads
from spyglass_service.radar.models import Assessment, AssistMessage, dumps

from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    make_settings,
    patch_fake_engine,
)
from .test_assist_threads import DOWN, script
from .test_feed_search import FakeIndex, make_item


def detail_up(db, item_id: int, **fields) -> None:
    """Set fields on an item's assessment."""
    with Session(db) as session:
        row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).one()
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()


@pytest.fixture
def world(db):
    """Three capsule items, one robot item and a fake index over them."""
    index = FakeIndex()
    with Session(db) as session:
        ids = [make_item(session, index, f"Capsule endoscopy study {n}", topic="capsule",
                         headline=f"Headline {n}") for n in range(3)]
        robot = make_item(session, index, "Robot assisted surgery", topic="robot", age_days=2)
    detail_up(db, ids[0], why="Directly on your field.", section="health",
              key_points=dumps(["First", "Second", "Third"]))
    return db, index, ids, robot


def block(db, index, **kw):
    """The feed block for a question."""
    return feed_context.build_feed_block(db, index, question=kw.pop("question", "capsule"), **kw)


def test_block_lists_retrieved_items_with_markers_and_details(world):
    db, index, ids, robot = world
    text, shown = block(db, index, question="What do I have about capsule endoscopy?")
    assert text.startswith(feed_context.FEED_MARKER)
    assert set(shown) == set(ids) and robot not in shown
    first = text[text.index(f"[#{ids[0]}]"):].split("\n\n")[0]
    assert "Headline 0" in first
    assert "tier notable" in first and "Why it matters: Directly on your field." in first
    assert "- First" in first and "- Second" in first and "- Third" not in first


def test_block_says_so_when_nothing_is_close(world):
    db, index, _ids, _robot = world
    text, shown = block(db, index, question="zebra migration patterns")
    assert shown == [] and feed_context.EMPTY_NOTE in text
    assert "[#" not in text


def test_block_is_capped_in_items_and_characters(db):
    index = FakeIndex()
    with Session(db) as session:
        made = [make_item(session, index, f"Capsule item {n}", topic="capsule") for n in range(40)]
    for item_id in made:
        detail_up(db, item_id, why="w" * 900, key_points=dumps(["p" * 900, "q" * 900]))
    text, shown = block(db, index)
    assert 0 < len(shown) <= feed_context.FEED_ITEMS_MAX
    assert len(text) <= feed_context.FEED_BLOCK_CHARS
    # Not everything fit: the character cap, not only the item cap, cut the list.
    assert len(shown) < feed_context.FEED_ITEMS_MAX


def test_item_cap_alone_limits_a_short_list(db):
    index = FakeIndex()
    with Session(db) as session:
        for n in range(40):
            make_item(session, index, f"Capsule item {n}", topic="capsule")
    _text, shown = block(db, index)
    assert len(shown) == feed_context.FEED_ITEMS_MAX


def test_selection_is_part_of_the_retrieval_query(world):
    db, index, ids, robot = world
    joined = feed_context.retrieval_query("tell me more", "capsule text")
    assert joined == "tell me more\ncapsule text"
    _text, shown = block(db, index, question="tell me more", selection="about robot surgery")
    assert robot in shown and ids[0] not in shown


def test_week_presets_use_recent_strong_items_not_similarity(world):
    db, index, ids, robot = world
    detail_up(db, robot, score=99)
    for action in ("feed_week", "feed_themes"):
        text, shown = block(db, index, question="zebras", action=action)
        assert shown[0] == robot and set(ids) <= set(shown), action
        assert feed_context.EMPTY_NOTE not in text
    assert set(feed_context.ACTIONS) == {"feed_week", "feed_themes"}
    assert set(feed_context.ACTIONS) <= set(context.action_names())
    assert "Five items at most" in context.build_turn("", None, "feed_week")


def test_system_prompt_for_a_feed_thread_and_for_an_item_thread(world):
    db, index, ids, _robot = world
    text, _ = block(db, index)
    system = context.build_system(db, feed_block=text)
    assert system.index(feed_context.INSTRUCTIONS) < system.index(feed_context.FEED_MARKER)
    assert "[#123]" in feed_context.INSTRUCTIONS
    assert "never invent" in feed_context.INSTRUCTIONS.lower()
    # A thread with neither a target nor a block keeps the plain prompt; an item thread ignores it.
    assert feed_context.FEED_MARKER not in context.build_system(db)
    item_system = context.build_system(db, item_id=ids[0], feed_block=text)
    assert feed_context.FEED_MARKER not in item_system and "=== THE ITEM ===" in item_system


def test_fence_wraps_the_list_but_not_the_instructions(world, tmp_path):
    db, index, ids, _robot = world
    text, _ = block(db, index)
    sent, _messages = privacy.prepare_assistant_call(
        context.build_system(db, feed_block=text), [], make_settings(Path(tmp_path)))
    fence_start = sent.rindex("<spyglass_material>")
    assert sent.index(feed_context.INSTRUCTIONS) < fence_start < sent.index(f"[#{ids[0]}]")
    assert sent.rstrip().endswith("</spyglass_material>")


def run(db, tmp_path, tid, index, **kw):
    """One turn on a feed thread with a fake index; returns the events."""
    return list(threads.run_turn(db, make_settings(tmp_path), tid,
                                 content=kw.pop("content", "capsule"), transport=DOWN,
                                 index_provider=lambda: index, **kw))


def test_turn_on_a_feed_thread_sends_items_and_reports_what_was_retrieved(world, tmp_path,
                                                                           monkeypatch):
    db, index, ids, _robot = world
    engine = FakeEngine(script("It is ", f"[#{ids[0]}]."))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db)["id"]
    events = run(db, tmp_path, tid, index, content="What do I have about capsule endoscopy?")
    done = events[-1]
    assert done["type"] == "done"
    assert {r["id"] for r in done["retrieved"]} == set(ids)
    assert all(r["headline"] for r in done["retrieved"])
    system = engine.calls[0]["system"]
    assert f"[#{ids[0]}] Headline 0" in system and "<spyglass_material>" in system
    assert system.index("Cite every claim") < system.rindex("<spyglass_material>")
    detail = threads.thread_detail(db, tid)
    assert {r["id"] for r in detail["retrieved"]} == set(ids)
    assert detail["messages"][-1]["content"] == f"It is [#{ids[0]}]."


def test_empty_feed_turn_tells_the_model_nothing_is_close(world, tmp_path, monkeypatch):
    db, index, _ids, _robot = world
    engine = FakeEngine(script("Nothing."))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db)["id"]
    events = run(db, tmp_path, tid, index, content="zebra migration patterns")
    assert events[-1]["retrieved"] == []
    assert feed_context.EMPTY_NOTE in engine.calls[0]["system"]


def test_week_preset_turn_and_follow_up_keep_earlier_items(world, tmp_path, monkeypatch):
    db, index, ids, robot = world
    engine = FakeEngine(script("ok"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db)["id"]
    run(db, tmp_path, tid, index, content="", action="feed_week")
    run(db, tmp_path, tid, index, content="zebra migration patterns")
    assert "Five items at most" in engine.calls[0]["messages"][-1]["content"]
    remembered = {r["id"] for r in threads.thread_detail(db, tid)["retrieved"]}
    assert {robot, *ids} == remembered


def test_missing_index_falls_back_to_text(world, tmp_path, monkeypatch):
    db, _index, ids, _robot = world
    engine = FakeEngine(script("ok"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db)["id"]

    def broken():
        raise RuntimeError("no model")

    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="capsule endoscopy",
                                   transport=DOWN, index_provider=broken))
    assert events[-1]["type"] == "done"
    assert {r["id"] for r in events[-1]["retrieved"]} == set(ids)


def test_search_failure_stores_an_error_and_never_calls_the_engine(world, tmp_path, monkeypatch):
    db, index, _ids, _robot = world
    engine = FakeEngine(script("never"))
    patch_fake_engine(monkeypatch, engine)

    def boom(*args, **kwargs):
        raise RuntimeError("database locked")

    monkeypatch.setattr("spyglass_service.radar.assist.feed_context.build_feed_block", boom)
    tid = threads.create_or_get_thread(db)["id"]
    events = run(db, tmp_path, tid, index)
    assert events == [{"type": "error", "message": "Could not search the feed just now."}]
    assert engine.calls == []
    with Session(db) as session:
        last = session.exec(select(AssistMessage).order_by(AssistMessage.id.desc())).first()
    assert last.role == "assistant" and last.error


def test_item_thread_has_no_feed_context_and_no_retrieved(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    engine = FakeEngine(script("ok"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="hi", transport=DOWN))
    assert "retrieved" not in events[-1] and "retrieved" not in threads.thread_detail(db, tid)
    assert feed_context.FEED_MARKER not in engine.calls[0]["system"]


@pytest.fixture
def client(db, tmp_path):
    """A small app with only the assistant router."""
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine = db
    app.state.settings = make_settings(tmp_path)
    return TestClient(app)


def test_post_threads_scopes(client):
    first = client.post("/api/radar/threads").json()
    assert first["thread"]["item_id"] is None and first["thread"]["brief_day"] is None
    assert first["retrieved"] == []
    assert client.post("/api/radar/threads", json={}).json()["thread"]["id"] == first["thread"]["id"]
    scoped = client.post("/api/radar/threads", json={"scope": "feed"}).json()
    assert scoped["thread"]["id"] == first["thread"]["id"]
    fresh = client.post("/api/radar/threads", json={"new": True}).json()
    assert fresh["thread"]["id"] != first["thread"]["id"]
    assert client.post("/api/radar/threads", json={}).json()["thread"]["id"] == fresh["thread"]["id"]


def test_post_threads_rejects_a_feed_scope_with_a_target(client, db):
    item_id = add_item(db)
    both = client.post("/api/radar/threads", json={"scope": "feed", "item_id": item_id})
    assert both.status_code == 422
    assert client.post("/api/radar/threads", json={"scope": "everything"}).status_code == 422


def test_message_endpoint_accepts_the_feed_presets_and_rejects_others(client, monkeypatch):
    engine = FakeEngine(script("ok"))
    patch_fake_engine(monkeypatch, engine)
    tid = client.post("/api/radar/threads").json()["thread"]["id"]
    ok = client.post(f"/api/radar/threads/{tid}/messages", json={"action": "feed_week"})
    assert ok.status_code == 200
    frames = [json.loads(line[6:]) for line in ok.text.splitlines() if line.startswith("data: ")]
    assert frames[-1]["type"] == "done" and frames[-1]["retrieved"] == []
    bad = client.post(f"/api/radar/threads/{tid}/messages", json={"action": "feed_year"})
    assert bad.status_code == 422
