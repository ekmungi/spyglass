"""Tests for build_server, the one place both the developer entry and the tray launcher build the
service, so they cannot drift apart."""

from fastapi.testclient import TestClient

import spyglass_service.__main__ as main_module
from spyglass_service.config import Settings


def make_settings(tmp_path) -> Settings:
    """Settings pointing all writable paths into the test's temp directory."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", port=7902)


def test_build_server_uses_three_second_graceful_wait(tmp_path) -> None:
    """Open MCP streams from Claude windows must not hold a stop past the three-second limit."""
    server = main_module.build_server(make_settings(tmp_path))
    assert main_module.STOP_WAIT_S == 3
    assert server.config.timeout_graceful_shutdown == 3
    assert server.config.host == "127.0.0.1"
    assert server.config.port == 7902


def test_build_server_marks_who_started_the_service(tmp_path) -> None:
    """The default is the developer entry; the launcher passes "desktop"."""
    default = main_module.build_server(make_settings(tmp_path / "a"))
    desktop = main_module.build_server(make_settings(tmp_path / "b"), started_by="desktop")
    assert default.config.app.state.started_by == "developer"
    assert desktop.config.app.state.started_by == "desktop"


def test_build_server_passes_extra_app_kwargs_to_the_app(tmp_path) -> None:
    """The launcher can inject things the developer entry does not need, such as a test opener."""
    opened: list[str] = []
    server = main_module.build_server(
        make_settings(tmp_path), extra_app_kwargs={"open_external": opened.append})
    assert server.config.app.state.open_external == opened.append


def test_shutdown_route_sets_should_exit_and_calls_on_stop(tmp_path) -> None:
    """POST /api/shutdown stops the server first, then tells the host (the tray) it is stopping."""
    seen: list[bool] = []
    server_box: dict = {}

    def on_stop() -> None:
        seen.append(server_box["server"].should_exit)

    server = main_module.build_server(make_settings(tmp_path), on_stop=on_stop)
    server_box["server"] = server
    with TestClient(server.config.app) as client:
        assert client.post("/api/shutdown").json() == {"status": "stopping"}
    assert server.should_exit is True
    assert seen == [True]
