"""Tests for the live Slack listener's connection lifecycle, configuration and status."""

# ruff: noqa: F811
import threading

import httpx

from spyglass_service.radar.sources.slack_live import BACKOFF_MAX, SlackLiveError, SlackLiveListener

from .test_sources_slack_live_support import (
    CHANNEL,
    HELLO,
    FakeSocket,
    Harness,
    configured,
    disconnect,
    envelope,
    make_settings,
    message,
    run,
)

# ---- connection lifecycle ------------------------------------------------------------------

def test_a_refresh_request_reconnects_at_once_without_waiting(engine):
    first = FakeSocket(HELLO, disconnect("refresh_requested"))
    second = FakeSocket(HELLO, envelope(message("1700000013.000100")))
    h = Harness(engine, configured(), [first, second])
    run(h)
    assert first.closed and len(h.captured) == 1
    assert h.events[:2] == ["open", "open"]  # reconnected straight away, no wait in between


def test_a_lost_connection_reconnects_with_growing_waits_capped(engine):
    sockets = [FakeSocket() for _ in range(9)]
    urls = [SlackLiveError("ratelimited")] * 9
    h = Harness(engine, configured(), sockets, urls=urls)
    run(h)
    assert h.waits[:6] == [1, 2, 4, 8, 16, 32]
    assert max(h.waits) == BACKOFF_MAX


def test_the_wait_starts_over_after_a_connection_that_worked(engine):
    sockets = [FakeSocket(), FakeSocket(), FakeSocket(HELLO), FakeSocket()]
    h = Harness(engine, configured(), sockets)
    run(h)
    assert h.waits[:2] == [1, 2]
    assert h.waits[2] == 1


def test_a_fatal_slack_error_waits_long_and_is_reported(engine):
    h = Harness(engine, configured(), [], urls=[SlackLiveError("invalid_auth", fatal=True)])
    run(h)
    assert h.waits[0] >= 300
    assert "invalid_auth" in (h.listener.status()["last_error"] or "")


def test_a_network_error_while_opening_is_retried(engine):
    h = Harness(engine, configured(), [FakeSocket(HELLO)], urls=[httpx.ConnectError("down")])
    run(h)
    assert h.waits[0] == 1 and h.opened >= 2


def test_stop_while_connecting_does_not_hang_and_closes_the_late_socket(engine):
    release, entered = threading.Event(), threading.Event()
    late = FakeSocket(HELLO)

    def slow_connect(url: str):
        entered.set()
        release.wait(5)
        return late

    listener = SlackLiveListener(engine, configured(), on_capture=lambda i: None,
                                 connect=slow_connect, open_url=lambda: "wss://x.slack.com/l")
    assert listener.start() is True
    assert entered.wait(2)
    listener.stop(timeout=0.2)
    release.set()
    listener._thread.join(2)  # noqa: SLF001
    assert late.closed and not listener.status()["running"]


def test_stop_during_a_backoff_wait_ends_the_thread(engine):
    listener = SlackLiveListener(engine, configured(), on_capture=lambda i: None,
                                 connect=lambda u: FakeSocket(),
                                 open_url=lambda: (_ for _ in ()).throw(SlackLiveError("x")))
    listener.start()
    listener.stop(timeout=2)
    assert not listener.status()["running"]


def test_stop_closes_the_open_socket(engine):
    connected = threading.Event()
    sock = FakeSocket(HELLO, "BLOCK")
    listener = SlackLiveListener(engine, configured(), on_capture=lambda i: None,
                                 connect=lambda u: (connected.set(), sock)[1],
                                 open_url=lambda: "wss://x.slack.com/l")
    listener.start()
    assert connected.wait(2)
    listener.stop(timeout=3)
    assert sock.closed and not listener.status()["running"]


# ---- configuration and status --------------------------------------------------------------

def test_start_refuses_without_an_app_token_or_channel(engine):
    for settings in (make_settings(slack_app_token=None, slack_capture_channel=CHANNEL),
                     make_settings(slack_app_token="xapp-1", slack_capture_channel="")):
        listener = SlackLiveListener(engine, settings, on_capture=lambda i: None)
        assert listener.start() is False
        status = listener.status()
        assert status["configured"] is False and status["running"] is False


def test_status_reports_the_connection_and_the_counts(engine):
    h = Harness(engine, configured(), [FakeSocket(HELLO, envelope(message("1700000014.000100")))])
    assert h.listener.status()["connected"] is False
    run(h)
    status = h.listener.status()
    assert status["configured"] is True and status["captured"] == 1
    assert status["last_event_at"] is not None and status["connected"] is False


def test_start_twice_runs_one_thread(engine):
    release = threading.Event()
    listener = SlackLiveListener(engine, configured(), on_capture=lambda i: None,
                                 connect=lambda u: (release.wait(2), FakeSocket())[1],
                                 open_url=lambda: "wss://x.slack.com/l")
    assert listener.start() and listener.start()
    first = listener._thread  # noqa: SLF001
    listener.start()
    assert listener._thread is first  # noqa: SLF001
    release.set()
    listener.stop(timeout=2)


def test_a_disconnect_before_any_hello_is_not_reconnected_in_a_hot_loop(engine):
    sockets = [FakeSocket(disconnect("warning")) for _ in range(3)]
    h = Harness(engine, configured(), sockets)
    run(h)
    assert h.waits[:3] == [1, 2, 4]
