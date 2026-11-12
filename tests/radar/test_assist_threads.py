# ruff: noqa: F811
"""Tests for assistant threads, the streamed turn, and the SSE endpoint."""

import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.radar.api import assist as assist_api
from spyglass_service.radar.agy_cli import TOOL_REFUSED
from spyglass_service.radar.assist import threads
from spyglass_service.radar.assist.engines.antigravity import TOOL_AFTER_TEXT
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.models import AssistMessage, AssistThread, Signal

from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    delta,
    make_settings,
    patch_fake_engine,
    sse_body,
)


# Local servers (Ollama, LM Studio) must look "not running" whatever runs on this machine.
DOWN = httpx.MockTransport(lambda req: httpx.Response(404))


def script(*pieces: str, session: str | None = None, end: StreamEvent | None = None):
    """Events for a normal answer made of `pieces`."""
    events = [StreamEvent.session(session)] if session else []
    events += [StreamEvent.delta(p) for p in pieces]
    return [*events, end or StreamEvent.done()]


def ask(db, tmp_path, thread_id, **kw) -> list[dict]:
    """Run one turn and collect its event dicts."""
    kw.setdefault("transport", DOWN)
    return list(threads.run_turn(db, make_settings(tmp_path), thread_id,
                                 content=kw.pop("content", "What is this?"), **kw))


def messages_of(db, thread_id) -> list[AssistMessage]:
    """All stored messages of a thread."""
    with Session(db) as session:
        return list(session.exec(select(AssistMessage).where(
            AssistMessage.thread_id == thread_id).order_by(AssistMessage.id)).all())


def test_create_or_get_returns_latest_unless_new(db):
    item_id = add_item(db)
    first = threads.create_or_get_thread(db, item_id=item_id)
    assert threads.create_or_get_thread(db, item_id=item_id)["id"] == first["id"]
    second = threads.create_or_get_thread(db, item_id=item_id, new=True)
    assert second["id"] != first["id"]
    assert threads.create_or_get_thread(db, item_id=item_id)["id"] == second["id"]
    day = threads.create_or_get_thread(db, brief_day="2026-11-12")
    assert day["id"] not in (first["id"], second["id"]) and day["item_id"] is None
    assert threads.thread_detail(db, 9999) is None


def test_turn_stores_both_messages_and_session_and_records_signal(db, tmp_path, monkeypatch):
    item_id = add_item(db, text="The robot cut precisely.")
    engine = FakeEngine(script("Hel", "lo", session="SESS-1"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    events = ask(db, tmp_path, tid, content="  Explain the cut  ", selection="cut precisely")
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    detail = threads.thread_detail(db, tid)
    user, answer = detail["messages"]
    assert user["role"] == "user" and user["selection"] == "cut precisely"
    assert answer["content"] == "Hello" and answer["engine"] == "fake" and answer["model"] == "m1"
    assert answer["error"] is None and events[-1]["message_id"] == answer["id"]
    assert detail["thread"]["title"].startswith("Explain the cut")
    assert detail["thread"]["engine"] == "fake"
    call = engine.calls[0]
    assert "The robot cut precisely." in call["system"] and call["session"] is None
    assert call["messages"][-1]["content"].startswith("The reader selected this passage:\n> cut")
    with Session(db) as session:
        assert session.get(AssistThread, tid).external_session == "SESS-1"
        asks = session.exec(select(Signal).where(Signal.kind == "ask")).all()
    assert len(asks) == 1 and asks[0].item_id == item_id and engine.closed


def test_second_turn_sends_history_and_resumes_the_session(db, tmp_path, monkeypatch):
    engine = FakeEngine(script("A1", session="S"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    ask(db, tmp_path, tid, content="first")
    engine.events = script("A2")
    ask(db, tmp_path, tid, content="second", action="explain")
    second = engine.calls[1]
    assert second["session"] == "S"
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"] == "A1"
    assert "plain language" in second["messages"][2]["content"]
    assert messages_of(db, tid)[-2].action == "explain"


def test_switching_engine_mid_thread_drops_the_old_session(db, tmp_path, monkeypatch):
    first = FakeEngine(script("x", session="S"), id="one")
    patch_fake_engine(monkeypatch, first)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    ask(db, tmp_path, tid)
    second = FakeEngine(script("y"), id="two")
    patch_fake_engine(monkeypatch, second)
    monkeypatch.setattr("spyglass_service.radar.assist.registry.list_engines",
                        lambda s, session=None, transport=None: [
                            {"id": "two", "label": "Two", "available": True, "reason": None,
                             "models": [{"id": "m1", "label": "m1"}], "default_model": "m1",
                             "is_default": False}])
    ask(db, tmp_path, tid, engine_id="two", model="m9")
    assert second.calls[0]["session"] is None and second.calls[0]["model"] == "m9"
    assert messages_of(db, tid)[-1].engine == "two"


def test_engine_error_keeps_partial_text_with_the_error(db, tmp_path, monkeypatch):
    engine = FakeEngine(script("part", end=StreamEvent.error("Provider is down.")))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    events = ask(db, tmp_path, tid)
    assert events[-1] == {"type": "error", "message": "Provider is down."}
    saved = messages_of(db, tid)[-1]
    assert saved.content == "part" and saved.error == "Provider is down."


@pytest.mark.parametrize("reason", [TOOL_REFUSED, TOOL_AFTER_TEXT])
def test_a_refused_tool_attempt_drops_the_text_streamed_before_it(db, tmp_path, monkeypatch, reason):
    """Text produced before a tool attempt is not stored: empty content, the error set, error event."""
    engine = FakeEngine(script("I will look", " this up", end=StreamEvent.error(reason)))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    events = ask(db, tmp_path, tid)
    assert events[-1] == {"type": "error", "message": reason}
    saved = messages_of(db, tid)[-1]
    assert saved.content == "" and saved.error == reason


def test_unexpected_engine_exception_becomes_a_short_error(db, tmp_path, monkeypatch):
    class Boom(FakeEngine):
        def stream(self, **kw):
            yield StreamEvent.delta("x")
            raise ValueError("secret stack detail sk-123")

    patch_fake_engine(monkeypatch, Boom([]))
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    events = ask(db, tmp_path, tid)
    assert events[-1]["type"] == "error" and "sk-123" not in json.dumps(events)
    assert messages_of(db, tid)[-1].error == "The assistant failed unexpectedly."


def test_closing_the_turn_early_stores_the_partial_answer_and_closes_the_engine(
        db, tmp_path, monkeypatch):
    engine = FakeEngine(script("one", "two", "three"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    turn = threads.run_turn(db, make_settings(tmp_path), tid, content="q")
    assert next(turn)["text"] == "one"
    turn.close()
    saved = messages_of(db, tid)[-1]
    assert saved.content == "one" and saved.error and "Stopped" in saved.error and engine.closed


def test_no_engine_configured_is_a_stored_error(db, tmp_path):
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    events = ask(db, tmp_path, tid)
    assert events[-1]["type"] == "error" and "No assistant engine" in events[-1]["message"]
    assert [m.role for m in messages_of(db, tid)] == ["user", "assistant"]


def test_unknown_thread_raises(db, tmp_path):
    with pytest.raises(threads.ThreadNotFound):
        ask(db, tmp_path, 404)


# ---- HTTP endpoint -------------------------------------------------------------------------


def make_client(db, tmp_path, monkeypatch, handler):
    """A TestClient on an app with only the assistant router and OpenRouter faked by `handler`."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings = db, make_settings(tmp_path)
    app.state.assist_transport = httpx.MockTransport(handler)
    return TestClient(app)


def chat_handler(body: bytes, status: int = 200):
    """Answer chat completions with `body`; everything else (local probes) with an empty reply."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/chat/completions"):
            return httpx.Response(status, content=body)
        return httpx.Response(404)
    return handler


def frames(response) -> list[dict]:
    """The data frames of an SSE response."""
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def test_post_message_streams_sse_and_stores_the_answer(db, tmp_path, monkeypatch):
    client = make_client(db, tmp_path, monkeypatch,
                         chat_handler(sse_body(delta("Hi "), delta("there"), comments=True)))
    item_id = add_item(db)
    thread = client.post("/api/radar/threads", json={"item_id": item_id}).json()["thread"]
    response = client.post(f"/api/radar/threads/{thread['id']}/messages",
                           json={"content": "Hello?", "engine": "openrouter",
                                 "model": "anthropic/claude-haiku-5.5"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = frames(response)
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert "".join(e.get("text", "") for e in events) == "Hi there"
    detail = client.get(f"/api/radar/threads/{thread['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "Hi there"
    assert detail["messages"][1]["model"] == "anthropic/claude-haiku-5.5"
    assert events[-1]["message_id"] == detail["messages"][1]["id"]


def test_post_message_engine_failure_is_an_error_event_with_no_secret(db, tmp_path, monkeypatch):
    err = json.dumps({"error": {"message": "bad key sk-or-test"}}).encode()
    client = make_client(db, tmp_path, monkeypatch, chat_handler(err, status=401))
    tid = client.post("/api/radar/threads", json={"item_id": add_item(db)}).json()["thread"]["id"]
    response = client.post(f"/api/radar/threads/{tid}/messages", json={"content": "q"})
    events = frames(response)
    assert events[-1]["type"] == "error" and "HTTP 401" in events[-1]["message"]
    stored = client.get(f"/api/radar/threads/{tid}").json()["messages"][-1]
    assert stored["error"] and stored["content"] == ""


def test_post_message_validation_and_unknown_thread(db, tmp_path, monkeypatch):
    client = make_client(db, tmp_path, monkeypatch, chat_handler(sse_body(delta("x"))))
    assert client.post("/api/radar/threads/999/messages", json={"content": "q"}).status_code == 404
    tid = client.post("/api/radar/threads", json={"item_id": add_item(db)}).json()["thread"]["id"]
    url = f"/api/radar/threads/{tid}/messages"
    assert client.post(url, json={"content": "  "}).status_code == 422
    assert client.post(url, json={"content": "q", "action": "bogus"}).status_code == 422
    assert client.post(url, json={"action": "explain", "extra": 1}).status_code == 422
    assert client.get("/api/radar/threads/999").status_code == 404
    assert client.post("/api/radar/threads", json={"item_id": 424242}).status_code == 404
    assert client.post("/api/radar/threads", json={"brief_day": "tomorrow"}).status_code == 422


def test_action_only_message_uses_the_preset_as_title_and_instruction(db, tmp_path, monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/chat/completions"):
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, content=sse_body(delta("ok")))
        return httpx.Response(404)

    client = make_client(db, tmp_path, monkeypatch, handler)
    tid = client.post("/api/radar/threads", json={"item_id": add_item(db)}).json()["thread"]["id"]
    client.post(f"/api/radar/threads/{tid}/messages", json={"action": "linkedin"})
    last = seen["body"]["messages"][-1]["content"]
    # Anthropic models behind OpenRouter get their last message as a cache-marked content block.
    assert "LinkedIn post" in (last if isinstance(last, str) else last[0]["text"])
    assert seen["body"]["messages"][0]["role"] == "system"
    assert client.get(f"/api/radar/threads/{tid}").json()["thread"]["title"] == "linkedin"


def test_pump_stops_and_closes_the_turn_when_the_client_is_gone(db, tmp_path, monkeypatch):
    import asyncio

    engine = FakeEngine(script("a", "b", "c", "d"))
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]

    async def scenario() -> list:
        loop = asyncio.get_running_loop()
        out: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()
        stop.set()  # the client disconnected before anything was delivered
        turn = threads.run_turn(db, make_settings(tmp_path), tid, content="q")
        worker = threading.Thread(target=assist_api._pump, args=(turn, loop, out, stop))
        worker.start()
        await loop.run_in_executor(None, worker.join)
        await asyncio.sleep(0.05)
        items = []
        while not out.empty():
            items.append(out.get_nowait())
        return items

    items = asyncio.run(scenario())
    assert items == [assist_api._END]
    assert engine.closed
    assert "Stopped" in (messages_of(db, tid)[-1].error or "")
