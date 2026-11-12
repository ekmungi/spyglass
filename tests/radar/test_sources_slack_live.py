"""Tests for the live Slack listener: capturing, the shared watermark and catching up.

NOTE: nothing here has run against Slack. The envelope and disconnect shapes follow Slack's
Socket Mode documentation; the real service was not reachable (no tokens).
"""

# ruff: noqa: F811
import json

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import ItemState
from spyglass_service.radar.sources import slack as slack_mod
from spyglass_service.radar.sources import slack_live

from .test_sources_slack_live_support import (
    CHANNEL,
    HELLO,
    FakeSocket,
    Harness,
    configured,
    envelope,
    make_settings,
    message,
    run,
)
from .test_sources_support import all_items

# ---- capturing -----------------------------------------------------------------------------

def test_a_human_message_with_a_link_is_acknowledged_then_captured(engine, monkeypatch):
    order: list[str] = []
    sock = FakeSocket(HELLO, envelope(message("1700000000.000100")))
    h = Harness(engine, configured(), [sock])
    original_send, original_capture = sock.send, slack_live.capture_url
    monkeypatch.setattr(sock, "send", lambda data: (order.append("ack"), original_send(data))[1])

    def spy(*args, **kwargs):
        order.append("capture")
        return original_capture(*args, **kwargs)

    monkeypatch.setattr(slack_live, "capture_url", spy)
    run(h)
    assert order[:2] == ["ack", "capture"]
    assert sock.sent[0] == {"envelope_id": "env-1"}
    items = all_items(engine, "capture")
    assert len(items) == 1 and items[0].url == "https://example.com/a"
    assert h.captured == [items[0].id]
    with Session(engine) as session:
        state = session.exec(select(ItemState)).one()
    assert state.captured_via == "slack" and "worth a look" in (state.user_note or "")


def test_every_link_in_one_message_is_captured_and_reported(engine):
    text = "<https://example.com/a> and <https://example.com/b|b>"
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000000.000100", text)))])
    run(h)
    assert len(h.captured) == 2 and len(all_items(engine, "capture")) == 2


@pytest.mark.parametrize("event", [
    message("1700000001.000100", bot_id="B1"),
    message("1700000001.000100", subtype="bot_message"),
    message("1700000001.000100", subtype="message_changed"),
    message("1700000001.000100", subtype="message_deleted"),
    message("1700000001.000100", subtype="channel_join"),
    {**message("1700000001.000100"), "channel": "C999"},
    {**message("1700000001.000100"), "type": "reaction_added"},
    message("1700000001.000200", thread_ts="1700000001.000100"),
], ids=["bot_id", "bot_message", "edit", "delete", "join", "other-channel", "other-event",
        "thread-reply"])
def test_events_that_are_not_new_human_messages_are_ignored_but_acknowledged(engine, event):
    sock = FakeSocket(HELLO, envelope(event))
    h = Harness(engine, configured(), [sock])
    run(h)
    assert all_items(engine, "capture") == [] and h.captured == []
    assert sock.sent == [{"envelope_id": "env-1"}]


def test_a_thread_broadcast_is_captured(engine):
    event = message("1700000002.000200", subtype="thread_broadcast", thread_ts="1700000002.000100")
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(event))])
    run(h)
    assert len(h.captured) == 1


def test_a_message_without_a_link_moves_the_watermark_but_captures_nothing(engine):
    h = Harness(engine, configured(),
                [FakeSocket(HELLO, envelope(message("1700000003.000100", "just thinking")))])
    run(h)
    assert h.captured == [] and slack_mod._load_watermark(engine) == "1700000003.000100"  # noqa: SLF001


def test_unknown_envelopes_are_acknowledged_and_junk_frames_are_skipped(engine):
    slash = json.dumps({"envelope_id": "e9", "type": "slash_commands", "payload": {}})
    sock = FakeSocket(HELLO, "not json", json.dumps([1, 2]), slash)
    run(Harness(engine, configured(), [sock]))
    assert sock.sent == [{"envelope_id": "e9"}]


def test_a_failing_on_capture_callback_does_not_stop_the_listener(engine):
    sock = FakeSocket(HELLO, envelope(message("1700000004.000100"), "e1"),
                      envelope(message("1700000004.000200", "<https://example.com/b>"), "e2"))
    h = Harness(engine, configured(), [sock])
    calls = []

    def boom(item_id: int) -> None:
        calls.append(item_id)
        raise RuntimeError("callback bug")

    h.listener._on_capture = boom  # noqa: SLF001
    run(h)
    assert len(calls) == 2


# ---- the watermark shared with the timer-based reader --------------------------------------

def test_the_watermark_is_the_same_one_the_timer_reader_uses(engine):
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000005.000100")))])
    run(h)
    assert slack_mod._load_watermark(engine) == "1700000005.000100"  # noqa: SLF001


def test_a_message_the_timer_already_handled_is_not_captured_again(engine):
    slack_mod._save_watermark(engine, "1700000006.000500")  # noqa: SLF001
    sock = FakeSocket(HELLO, envelope(message("1700000006.000100")),
                      envelope(message("1700000006.000500")))
    h = Harness(engine, configured(), [sock])
    run(h)
    assert h.captured == [] and all_items(engine, "capture") == []


def test_the_timer_reader_skips_what_the_listener_handled(engine):
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000007.000100")))])
    run(h)
    asked: list[dict] = []

    def transport(url: str, params: dict) -> dict:
        asked.append(params)
        return {"ok": True, "messages": []}

    slack_mod.collect_slack(engine, make_settings(slack_bot_token="xoxb", slack_capture_channel=CHANNEL),
                            transport=transport)
    assert asked[0]["oldest"] == "1700000007.000100"


def test_the_same_message_delivered_twice_is_captured_once(engine):
    sock = FakeSocket(HELLO, envelope(message("1700000008.000100"), "e1"),
                      envelope(message("1700000008.000100"), "e1"))
    h = Harness(engine, configured(), [sock])
    run(h)
    assert len(h.captured) == 1 and len(sock.sent) == 2


def test_an_unexpected_capture_failure_holds_the_watermark(engine, monkeypatch):
    calls = {"n": 0}
    real = slack_live.capture_url

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database busy")
        return real(*args, **kwargs)

    monkeypatch.setattr(slack_live, "capture_url", flaky)
    sock = FakeSocket(HELLO, envelope(message("1700000009.000100"), "e1"),
                      envelope(message("1700000009.000200", "<https://example.com/b>"), "e2"))
    h = Harness(engine, configured(), [sock])
    run(h)
    assert len(h.captured) == 1  # the second message was still captured
    assert slack_mod._load_watermark(engine) is None  # noqa: SLF001  (first is retried later)


def test_a_rejected_link_is_skipped_and_the_watermark_moves_on(engine):
    bad = message("1700000010.000100", "<http://127.0.0.1/admin>")
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(bad))])
    run(h)
    assert h.captured == [] and slack_mod._load_watermark(engine) == "1700000010.000100"  # noqa: SLF001


# ---- catching up after a gap ---------------------------------------------------------------

def test_on_connect_the_listener_catches_up_on_messages_missed_while_away(engine):
    slack_mod._save_watermark(engine, "1700000011.000100")  # noqa: SLF001
    seen_oldest: list[str] = []

    def history(oldest: str) -> list[dict]:
        seen_oldest.append(oldest)
        return [{"type": "message", "user": "U1", "ts": "1700000011.000300",
                 "text": "<https://example.com/missed>"},
                {"type": "message", "bot_id": "B1", "ts": "1700000011.000400", "text": "<https://x.test>"}]

    h = Harness(engine, configured(), [FakeSocket(HELLO)], history=history)
    run(h)
    assert seen_oldest == ["1700000011.000100"]
    assert len(h.captured) == 1 and slack_mod._load_watermark(engine) == "1700000011.000300"  # noqa: SLF001


def test_a_failing_catch_up_is_reported_and_live_events_still_flow(engine):
    def history(oldest: str) -> list[dict]:
        raise RuntimeError("Slack error: missing_scope")

    sock = FakeSocket(HELLO, envelope(message("1700000012.000100")))
    h = Harness(engine, configured(), [sock], history=history)
    run(h)
    assert len(h.captured) == 1
    assert "missing_scope" in (h.listener.status()["last_error"] or "")


def test_nothing_is_handled_while_another_reader_holds_the_capture_lock(engine, monkeypatch):
    from spyglass_service.radar.sources._common import capture_sources_lock

    monkeypatch.setattr(slack_live, "LOCK_WAIT", 0.05)
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000015.000100")))])
    with capture_sources_lock:
        run(h)
    assert h.captured == [] and slack_mod._load_watermark(engine) is None  # noqa: SLF001
    assert capture_sources_lock.acquire(blocking=False)  # released again by everyone
    capture_sources_lock.release()


def test_the_capture_lock_is_free_while_the_callback_runs(engine):
    from spyglass_service.radar.sources._common import capture_sources_lock

    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000016.000100")))])
    free: list[bool] = []

    def callback(item_id: int) -> None:
        free.append(capture_sources_lock.acquire(blocking=False))
        if free[-1]:
            capture_sources_lock.release()

    h.listener._on_capture = callback  # noqa: SLF001
    run(h)
    assert free == [True]
