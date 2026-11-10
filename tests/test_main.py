"""Tests for the service entry point."""

from fastapi.testclient import TestClient

import spyglass_service.__main__ as main_module


class FakeServer:
    """Stands in for uvicorn.Server: records its config and whether it was asked to stop."""

    def __init__(self, config) -> None:
        self.config = config
        self.should_exit = False
        FakeServer.last = self

    def run(self) -> None:
        pass


def test_main_serves_app_on_configured_host_and_port(monkeypatch, tmp_path) -> None:
    """`python -m spyglass_service` starts uvicorn with the configured binding."""
    monkeypatch.setattr(main_module.uvicorn, "Server", FakeServer)
    monkeypatch.setenv("SPYGLASS_PORT", "7901")
    monkeypatch.setenv("SPYGLASS_DATA_DIR", str(tmp_path / "data"))

    main_module.main()

    config = FakeServer.last.config
    assert config.host == "127.0.0.1"
    assert config.port == 7901
    assert config.app.title == "Spyglass"
    # Open MCP streams from Claude sessions must not hold a stop forever.
    assert config.timeout_graceful_shutdown == main_module.STOP_WAIT_S


def test_the_shutdown_endpoint_stops_the_server(monkeypatch, tmp_path) -> None:
    """POST /api/shutdown used to answer "stopping" without stopping anything."""
    monkeypatch.setattr(main_module.uvicorn, "Server", FakeServer)
    monkeypatch.setenv("SPYGLASS_DATA_DIR", str(tmp_path / "data"))
    main_module.main()
    server = FakeServer.last
    with TestClient(server.config.app) as client:
        assert client.post("/api/shutdown").json() == {"status": "stopping"}
    assert server.should_exit is True
