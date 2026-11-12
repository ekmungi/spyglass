"""Tests for the Slack capture collector (fake transport; never run against a real workspace)."""

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import ItemState, RadarDoc, loads
from spyglass_service.radar.sources import slack as slack_mod
from spyglass_service.radar.sources._common import NotConfigured
from spyglass_service.radar.sources.slack import (
    collect_slack,
    extract_links,
    fetch_messages,
    message_note,
)

from .test_sources_support import all_items, make_engine, make_settings


def configured():
    return make_settings(slack_bot_token="xoxb-test", slack_capture_channel="C123")


@pytest.fixture(autouse=True)
def offline_capture(monkeypatch):
    """Captures resolve to a public address and skip the title fetch."""
    from spyglass_service.radar import capture

    monkeypatch.setattr(capture, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(capture, "_default_title", lambda url: "Title")


class FakeSlack:
    """Records calls and serves canned pages of history."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages, self.calls = list(pages), []

    def __call__(self, url: str, params: dict) -> dict:
        self.calls.append(params)
        return self.pages.pop(0)


def watermark(engine) -> str | None:
    with Session(engine) as session:
        row = session.get(RadarDoc, "slack_watermark")
        return loads(row.body)["ts"] if row else None


def test_extract_links_and_note_handle_slack_markup() -> None:
    text = "look <https://a.example/x?q=1&amp;r=2|this post> and <https://b.example> &gt; ok"
    assert extract_links(text) == ["https://a.example/x?q=1&r=2", "https://b.example"]
    assert message_note(text) == "look this post and > ok"
    assert extract_links("<mailto:a@b.c> <#C1|chan> none") == []
    assert message_note("<https://only.example>") is None


def test_fetch_messages_paginates_and_sorts_oldest_first() -> None:
    transport = FakeSlack([
        {"ok": True, "messages": [{"ts": "3"}, {"ts": "2"}], "has_more": True,
         "response_metadata": {"next_cursor": "cur"}},
        {"ok": True, "messages": [{"ts": "1"}], "has_more": False},
    ])
    messages = fetch_messages(transport, "C1", "0")
    assert [m["ts"] for m in messages] == ["1", "2", "3"]
    assert transport.calls[1]["cursor"] == "cur"


def test_fetch_messages_raises_on_slack_error() -> None:
    with pytest.raises(RuntimeError, match="invalid_auth"):
        fetch_messages(FakeSlack([{"ok": False, "error": "invalid_auth"}]), "C1", "0")


def test_not_configured_raises() -> None:
    with pytest.raises(NotConfigured):
        collect_slack(None, make_settings())


def test_collect_captures_links_with_notes_and_advances_the_watermark(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        transport = FakeSlack([{"ok": True, "has_more": False, "messages": [
            {"ts": "1794000002.0", "text": "second <https://example.org/two>"},
            {"ts": "1794000001.0", "text": "first <https://example.org/one|One>"},
            {"ts": "1794000003.0", "text": "no link here"},
            {"ts": "1794000004.0", "bot_id": "B1", "text": "<https://example.org/bot>"},
            {"ts": "1794000005.0", "text": "pic", "files": [{"id": "F1"}]},
        ]}])
        assert collect_slack(engine, configured(), transport=transport) == 2
        assert sorted(i.url for i in all_items(engine, "capture")) == [
            "https://example.org/one", "https://example.org/two"]
        with Session(engine) as session:
            states = session.exec(select(ItemState)).all()
            assert {s.captured_via for s in states} == {"slack"}
            assert {s.user_note for s in states} == {"first One", "second"}
        assert watermark(engine) == "1794000005.0"
        # The next poll asks only for newer messages.
        nxt = FakeSlack([{"ok": True, "has_more": False, "messages": []}])
        assert collect_slack(engine, configured(), transport=nxt) == 0
        assert nxt.calls[0]["oldest"] == "1794000005.0" and nxt.calls[0]["channel"] == "C123"
    finally:
        engine.dispose()


def test_first_run_reads_only_the_last_week(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        transport = FakeSlack([{"ok": True, "has_more": False, "messages": []}])
        collect_slack(engine, configured(), transport=transport)
        import time

        age = time.time() - float(transport.calls[0]["oldest"])
        assert 6.9 * 86400 < age < 7.1 * 86400
        assert watermark(engine) is None  # nothing handled, nothing stored
    finally:
        engine.dispose()


def test_rejected_link_still_advances_but_a_crash_holds_the_watermark(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path)
    try:
        page = {"ok": True, "has_more": False, "messages": [
            {"ts": "1794000001.0", "text": "<http://localhost/admin>"},
            {"ts": "1794000002.0", "text": "<https://example.org/ok>"},
            {"ts": "1794000003.0", "text": "<https://example.org/later>"},
        ]}
        real = slack_mod.capture_url

        def flaky(engine_, settings, url, **kw):
            if url.endswith("/ok"):
                raise RuntimeError("db locked")
            return real(engine_, settings, url, **kw)

        monkeypatch.setattr(slack_mod, "capture_url", flaky)
        assert collect_slack(engine, configured(), transport=FakeSlack([page])) == 0
        assert watermark(engine) == "1794000001.0"  # the crashed message is retried next time
        assert all_items(engine, "capture") == []
    finally:
        engine.dispose()
