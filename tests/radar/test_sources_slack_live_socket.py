"""The live listener over a real WebSocket, against a fake Slack server on the loopback address.

Only 127.0.0.1 is used: no traffic leaves this computer. It checks that the `websockets` calls
(connect, recv with a timeout, send, close, closed-connection handling) behave as the listener
assumes. It does not show anything about Slack itself.
"""

import json
import threading

import pytest
from websockets.sync.server import serve

from spyglass_service.radar.sources.slack_live import SlackLiveListener

from .test_sources_support import all_items, make_engine, make_settings


@pytest.fixture(autouse=True)
def offline_capture(monkeypatch):
    from spyglass_service.radar import capture

    monkeypatch.setattr(capture, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(capture, "_default_title", lambda url: "Title")


def test_listener_acknowledges_and_captures_over_a_real_socket(tmp_path):
    acks: list[dict] = []
    connections = {"n": 0}
    captured: list[int] = []
    done = threading.Event()

    def fake_slack(ws) -> None:
        connections["n"] += 1
        if connections["n"] > 1:
            ws.close()
            return
        ws.send(json.dumps({"type": "hello", "num_connections": 1}))
        event = {"type": "message", "channel": "C123", "user": "U1", "ts": "1700000100.000100",
                 "text": "<https://example.com/live> read this"}
        ws.send(json.dumps({"envelope_id": "e1", "type": "events_api",
                            "payload": {"type": "event_callback", "event": event}}))
        acks.append(json.loads(ws.recv(timeout=5)))
        ws.send(json.dumps({"type": "disconnect", "reason": "refresh_requested"}))
        done.wait(5)

    engine = make_engine(tmp_path)
    settings = make_settings(slack_app_token="xapp-test", slack_capture_channel="C123")
    with serve(fake_slack, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def on_capture(item_id: int) -> None:
            captured.append(item_id)
            done.set()

        listener = SlackLiveListener(engine, settings, on_capture=on_capture,
                                     open_url=lambda: f"ws://127.0.0.1:{port}")
        assert listener.start()
        assert done.wait(10), "no capture arrived"
        listener.stop(timeout=5)
        server.shutdown()
    assert acks == [{"envelope_id": "e1"}]
    assert len(captured) == 1 and all_items(engine, "capture")[0].url == "https://example.com/live"
    assert not listener.status()["running"]
    engine.dispose()
