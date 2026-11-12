# ruff: noqa: F811
"""Tests that each engine reports its token figures and that a chat turn records them."""

import json

import pytest

import httpx
from sqlmodel import Session, select

from spyglass_service.radar.assist import threads
from spyglass_service.radar.assist.engines.anthropic_api import AnthropicEngine
from spyglass_service.radar.assist.engines.base import USAGE, StreamEvent
from spyglass_service.radar.assist.engines.claude_code import parse_line
from spyglass_service.radar.assist.engines.openai_compat import OpenAICompatEngine
from spyglass_service.radar.usage import UsageCall
from spyglass_service.radar.usage_parse import Tokens

from .test_assist_support import (  # noqa: F401
    FakeEngine,
    add_item,
    clean_assist_env,
    db,
    delta,
    make_settings,
    patch_fake_engine,
    sse_body,
)

TOKENS = Tokens(input=2, cache_write=100, cache_read=900, output=40, cost_usd=0.01)


def stored(db) -> list[UsageCall]:
    """Every usage row, oldest first."""
    with Session(db) as session:
        return list(session.exec(select(UsageCall).order_by(UsageCall.id)).all())


def test_stream_event_usage_carries_the_tokens():
    event = StreamEvent.usage(TOKENS)
    assert event.kind == USAGE and event.data == TOKENS


def test_claude_result_line_emits_usage_then_done():
    line = json.dumps({"type": "result", "is_error": False, "session_id": "S1",
                       "total_cost_usd": 0.01,
                       "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100,
                                 "cache_read_input_tokens": 900, "output_tokens": 40}})
    events = parse_line(line, {})
    assert [e.kind for e in events] == ["session", "usage", "done"]
    assert events[1].data == TOKENS


def test_claude_error_result_emits_no_usage():
    line = json.dumps({"type": "result", "is_error": True, "result": "boom", "usage": {}})
    assert [e.kind for e in parse_line(line, {})] == ["error"]


def test_turn_records_usage_and_the_done_event_carries_it(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    engine = FakeEngine([StreamEvent.delta("Hi"), StreamEvent.usage(TOKENS), StreamEvent.done()])
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="What is this?"))
    done = events[-1]
    assert done["type"] == "done"
    assert done["usage"] == {"input_tokens": 2, "cache_write_tokens": 100,
                             "cache_read_tokens": 900, "output_tokens": 40, "context_tokens": 1002,
                             "cached_share": 900 / 1002, "cost_usd": 0.01}
    [row] = stored(db)
    assert (row.purpose, row.provider, row.model) == ("chat", "fake", "m1")
    assert (row.thread_id, row.message_id) == (tid, done["message_id"])
    assert row.cache_read_tokens == 900 and row.duration_ms is not None


def test_a_feed_conversation_is_recorded_as_feed_chat(db, tmp_path, monkeypatch):
    engine = FakeEngine([StreamEvent.delta("Hi"), StreamEvent.usage(TOKENS), StreamEvent.done()])
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db)["id"]
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="What happened?"))
    assert [r.purpose for r in stored(db)] == ["feed_chat"]


def test_a_turn_without_figures_still_records_a_row_and_has_no_usage_in_done(db, tmp_path,
                                                                             monkeypatch):
    item_id = add_item(db)
    patch_fake_engine(monkeypatch, FakeEngine([StreamEvent.delta("Hi"), StreamEvent.done()]))
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="Q"))
    assert "usage" not in events[-1]
    [row] = stored(db)
    assert row.input_tokens is None and row.message_id == events[-1]["message_id"]


def test_a_failed_turn_records_nothing(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    patch_fake_engine(monkeypatch, FakeEngine([StreamEvent.error("nope")]))
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="Q"))
    assert stored(db) == []


def test_openai_engine_asks_for_usage_and_reports_cached_tokens():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        usage = {"prompt_tokens": 1000, "completion_tokens": 7,
                 "prompt_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 100}}
        return httpx.Response(200, content=sse_body(
            delta("Hello"), {"choices": [], "usage": usage}),
            headers={"content-type": "text/event-stream"})

    engine = OpenAICompatEngine(id="openai", label="X", kind="api", base_url="https://example.org/v1",
                                key_required=False, models=[{"id": "m", "label": "m"}],
                                transport=httpx.MockTransport(handler))
    events = list(engine.stream(system="S", messages=[{"role": "user", "content": "Q"}], model="m"))
    assert seen["payload"]["stream_options"] == {"include_usage": True}
    [usage_event] = [e for e in events if e.kind == USAGE]
    assert usage_event.data == Tokens(input=100, cache_write=100, cache_read=800, output=7)
    assert events[-1].kind == "done"


def test_a_custom_server_is_not_sent_a_field_it_may_reject():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, content=sse_body(delta("Hello")),
                              headers={"content-type": "text/event-stream"})

    engine = OpenAICompatEngine(id="custom-x", label="X", kind="custom", base_url="http://127.0.0.1:9/v1",
                                key_required=False, models=[{"id": "m", "label": "m"}],
                                transport=httpx.MockTransport(handler))
    events = list(engine.stream(system="S", messages=[{"role": "user", "content": "Q"}], model="m"))
    assert "stream_options" not in seen["payload"]
    assert [e.kind for e in events] == ["delta", "done"]


def test_anthropic_engine_reports_cache_figures():
    body = "".join([
        "event: message_start\ndata: " + json.dumps({"type": "message_start", "message": {"usage": {
            "input_tokens": 12, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 0,
            "output_tokens": 1}}}) + "\n\n",
        "event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "delta": {
            "type": "text_delta", "text": "Hi"}}) + "\n\n",
        "event: message_delta\ndata: " + json.dumps({"type": "message_delta",
                                                      "usage": {"output_tokens": 88}}) + "\n\n",
        "event: message_stop\ndata: " + json.dumps({"type": "message_stop"}) + "\n\n",
    ]).encode()
    engine = AnthropicEngine(api_key="sk-test-key-123456", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=body,
                                       headers={"content-type": "text/event-stream"})))
    events = list(engine.stream(system="S", messages=[{"role": "user", "content": "Q"}],
                                model="claude-sonnet-5-5"))
    [usage_event] = [e for e in events if e.kind == USAGE]
    assert usage_event.data == Tokens(input=12, cache_write=500, cache_read=0, output=88)


def test_a_resumed_turn_records_only_its_own_cost(db, tmp_path, monkeypatch):
    # Claude Code reports the whole conversation's cost on a resumed turn; the table keeps the
    # share of this turn so that sums over turns are not counted twice.
    item_id = add_item(db)
    first = Tokens(input=2, cache_write=100, cache_read=0, output=5, cost_usd=0.010)
    second = Tokens(input=2, cache_write=10, cache_read=100, output=5, cost_usd=0.013)
    third = Tokens(input=2, cache_write=10, cache_read=110, output=5, cost_usd=0.0145)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    for tokens, session in ((first, "S1"), (second, "S1"), (third, "S1")):
        engine = FakeEngine([StreamEvent.session("S1"), StreamEvent.delta("Hi"),
                             StreamEvent.usage(tokens), StreamEvent.done()])
        patch_fake_engine(monkeypatch, engine)
        events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="Q"))
    costs = [r.cost_usd for r in stored(db)]
    assert costs == [pytest.approx(0.010), pytest.approx(0.003), pytest.approx(0.0015)]
    assert events[-1]["usage"]["cost_usd"] == pytest.approx(0.0015)
    assert [r.cost_total for r in stored(db)] == [0.010, 0.013, 0.0145]


def test_a_new_session_after_a_resumed_one_starts_its_cost_again(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    for cost, session in ((0.010, "S1"), (0.002, "S2")):
        engine = FakeEngine([StreamEvent.session(session), StreamEvent.delta("Hi"),
                             StreamEvent.usage(Tokens(input=1, output=1, cost_usd=cost)),
                             StreamEvent.done()])
        patch_fake_engine(monkeypatch, engine)
        list(threads.run_turn(db, make_settings(tmp_path), tid, content="Q"))
        with Session(db) as session_db:
            thread = session_db.get(threads.AssistThread, tid)
            thread.external_session = None  # the next turn starts a new session
            session_db.add(thread)
            session_db.commit()
    assert [r.cost_usd for r in stored(db)] == [0.010, 0.002]
