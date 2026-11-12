"""Shared helpers for the live Slack listener tests: a scripted socket and a harness (no tests)."""

import json
import threading

import pytest

from spyglass_service.radar.sources.slack_live import SlackLiveListener

from .test_sources_support import make_engine, make_settings

CHANNEL = "C123"


def configured(**overrides):
    return make_settings(slack_app_token="xapp-test", slack_bot_token=None,
                         slack_capture_channel=CHANNEL, **overrides)


@pytest.fixture(autouse=True)
def offline_capture(monkeypatch):
    """Captures resolve to a public address and skip the title fetch."""
    from spyglass_service.radar import capture

    monkeypatch.setattr(capture, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(capture, "_default_title", lambda url: "Title")


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def message(ts: str, text: str = "<https://example.com/a|a> worth a look", **extra) -> dict:
    """A Slack message event in the capture channel."""
    return {"type": "message", "channel": CHANNEL, "user": "U1", "ts": ts, "text": text, **extra}


def envelope(event: dict, envelope_id: str = "env-1") -> str:
    """An events_api envelope as Socket Mode delivers it."""
    return json.dumps({"envelope_id": envelope_id, "type": "events_api",
                       "accepts_response_payload": False,
                       "payload": {"type": "event_callback", "event": event}})


HELLO = json.dumps({"type": "hello", "num_connections": 1,
                    "debug_info": {"approximate_connection_time": 18060}})


def disconnect(reason: str = "refresh_requested") -> str:
    return json.dumps({"type": "disconnect", "reason": reason})


class FakeSocket:
    """A scripted socket: frames, exceptions or "TIMEOUT"; then the connection drops."""

    def __init__(self, *script, on_empty=None) -> None:
        self.script, self.sent, self.on_empty = list(script), [], on_empty
        self.log: list[str] = []
        self._closed = threading.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def recv(self, timeout=None):
        if self.script:
            item = self.script.pop(0)
            if item == "BLOCK":
                # Wait like a real socket: a close from another thread ends the wait.
                if self._closed.wait(5):
                    raise ConnectionError("closed")
                raise TimeoutError
            if item == "TIMEOUT":
                raise TimeoutError
            if isinstance(item, Exception):
                raise item
            return item
        if self.on_empty:
            self.on_empty()
        raise ConnectionError("closed")

    def send(self, data: str) -> None:
        self.sent.append(json.loads(data))
        self.log.append("send")

    def close(self) -> None:
        self._closed.set()


class Harness:
    """Builds a listener whose sockets, waits and captures are all fakes."""

    def __init__(self, engine, settings, sockets, *, history=None, urls=None) -> None:
        self.sockets, self.waits, self.captured, self.opened = list(sockets), [], [], 0
        self.events: list[str] = []
        self.urls = list(urls) if urls is not None else None
        self.listener = SlackLiveListener(
            engine, settings, on_capture=self.captured.append, connect=self._connect,
            open_url=self._open_url, wait=self._wait, fetch_history=history)

    def _open_url(self) -> str:
        self.opened += 1
        self.events.append("open")
        if self.urls:
            outcome = self.urls.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        return "wss://wss-primary.slack.com/link?ticket=t"

    def _connect(self, url: str):
        if not self.sockets:
            self.listener.stop()  # the script is over: end the run without recording an error
            return FakeSocket()
        return self.sockets.pop(0)

    def _wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.events.append("wait")
        if len(self.waits) > 40:
            self.listener.stop()
        return self.listener._stop.is_set()  # noqa: SLF001


def run(harness: Harness) -> None:
    harness.listener.run()
