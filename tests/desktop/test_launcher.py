"""Tests for the desktop launcher core: environment, start decision, logs, folder check."""

import json
import os
import socket
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from spyglass_service.desktop.__main__ import main
from spyglass_service.desktop.datadir import DesktopConfig, record_data_version
from spyglass_service.desktop.launcher import (
    Health,
    StartAction,
    decide_start,
    prepare_environment,
    probe_health,
    redirect_output,
    refusal_message,
    single_instance_lock,
)
from spyglass_service.radar.cycle_lock import CycleFileLock

DESKTOP = Health(version="0.41.0", started_by="desktop")
DEVELOPER = Health(version="0.40.0", started_by="developer")
LEGACY = Health(version="0.40.0", started_by=None)


@pytest.mark.parametrize("lock, health, expected", [
    (False, DESKTOP, StartAction.OPEN_PEER),
    (False, None, StartAction.OPEN_PEER),
    (False, DEVELOPER, StartAction.OPEN_PEER),
    (False, "not-spyglass", StartAction.OPEN_PEER),
    (True, DEVELOPER, StartAction.REFUSE_OTHER_SPYGLASS),
    (True, LEGACY, StartAction.REFUSE_OTHER_SPYGLASS),
    (True, DESKTOP, StartAction.REFUSE_OTHER_SPYGLASS),
    (True, "not-spyglass", StartAction.REFUSE_PORT_BUSY),
    (True, None, StartAction.START),
])
def test_decide_start(lock, health, expected) -> None:
    """Every row of the start decision table."""
    assert decide_start(lock, health) is expected


def test_refusal_message_for_a_spyglass_started_outside_the_app() -> None:
    """The wording is fixed by the spec and names the version found."""
    for health in (DEVELOPER, LEGACY):
        assert refusal_message(health, 7777) == (
            "Spyglass is already running outside the app (version 0.40.0), started from a "
            "command line, a script or the Obsidian plugin's Open dashboard. Stop it, then "
            "open Spyglass again."
        )


def test_refusal_message_for_another_install_on_the_same_port() -> None:
    """Another desktop install with a different data folder is named by version and port."""
    assert refusal_message(DESKTOP, 7790) == (
        "Another Spyglass (version 0.41.0) is already running on port 7790 with a different "
        "data folder. Quit it from its tray icon, then open Spyglass again."
    )


def test_prepare_environment_uses_overlay_port(tmp_path, monkeypatch) -> None:
    """The data folder's settings.json wins over the port the installer recorded."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text('{"port": 7791}')
    settings = prepare_environment(DesktopConfig(data_dir=tmp_path, port=7777), environ={})
    assert settings.port == 7791


def test_prepare_environment_sets_variables_and_working_directory(tmp_path, monkeypatch) -> None:
    """The service and the processes it starts see the data folder, port, vault and browser."""
    monkeypatch.chdir(tmp_path)
    data, vault = tmp_path / "data", tmp_path / "vault"
    data.mkdir()
    environ: dict[str, str] = {}
    settings = prepare_environment(
        DesktopConfig(data_dir=data, vault_path=vault, port=7792), environ=environ)
    assert environ["SPYGLASS_DATA_DIR"] == str(data)
    assert environ["SPYGLASS_PORT"] == "7792"
    assert environ["SPYGLASS_VAULT_PATH"] == str(vault)
    assert environ["SPYGLASS_BROWSER_CHANNEL"] == "msedge"
    assert Path.cwd().resolve() == data.resolve()
    assert settings.data_dir == data and settings.port == 7792
    assert settings.vault_path == vault and settings.browser_channel == "msedge"


def test_prepare_environment_leaves_vault_unset_without_one(tmp_path, monkeypatch) -> None:
    """No vault in the config means no vault variable is invented."""
    monkeypatch.chdir(tmp_path)
    environ: dict[str, str] = {}
    prepare_environment(DesktopConfig(data_dir=tmp_path), environ=environ)
    assert "SPYGLASS_VAULT_PATH" not in environ


class _Handler(BaseHTTPRequestHandler):
    """Answers every GET with the (status, body) the test put on the server."""

    def do_GET(self) -> None:  # noqa: N802 - the method name http.server looks for
        status, body = self.server.reply  # type: ignore[attr-defined]
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        """Keep the test output quiet."""


@pytest.fixture
def fake_service():
    """A throwaway local HTTP server on a free port; set .reply to (status, body bytes)."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.reply = (200, b"{}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_probe_health_reads_version_and_started_by(fake_service) -> None:
    """A JSON body with a version becomes a Health."""
    body = json.dumps({"status": "ok", "version": "0.41.0", "started_by": "desktop"})
    fake_service.reply = (200, body.encode())
    assert probe_health(fake_service.server_port) == Health("0.41.0", "desktop")


def test_probe_health_on_an_old_service_has_no_started_by(fake_service) -> None:
    """0.40.0 and older do not report who started them."""
    fake_service.reply = (200, b'{"status": "ok", "version": "0.40.0"}')
    assert probe_health(fake_service.server_port) == Health("0.40.0", None)


@pytest.mark.parametrize("status, body", [
    (200, b"<html>hello</html>"), (200, b'{"status": "ok"}'), (404, b"{}"), (500, b"oops"),
])
def test_probe_health_other_answers_are_not_spyglass(fake_service, status, body) -> None:
    """Anything else that answers HTTP is something other than Spyglass."""
    fake_service.reply = (status, body)
    assert probe_health(fake_service.server_port) == "not-spyglass"


def test_probe_health_returns_none_when_nothing_listens() -> None:
    """A refused connection means the port is free."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_port
    server.server_close()  # nothing listens on the port any more
    assert probe_health(port, timeout=0.5) is None


@pytest.fixture
def raw_service():
    """A raw TCP server on a free port. Set .script to a function taking the accepted socket."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.2)
    state = {"script": lambda conn: None, "stop": False, "held": []}

    def serve() -> None:
        while not state["stop"]:
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            state["held"].append(conn)
            conn.settimeout(2)
            try:
                conn.recv(4096)  # the request
                state["script"](conn)
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    state["port"] = listener.getsockname()[1]
    yield state
    state["stop"] = True
    thread.join(timeout=5)
    for conn in state["held"]:
        conn.close()
    listener.close()


def test_probe_health_non_http_bytes_are_not_spyglass(raw_service) -> None:
    """A service that answers with garbage instead of HTTP must not crash the probe."""
    def garbage(conn):
        conn.sendall(b"GARBAGE this is not http\r\n\r\n")
        conn.close()

    raw_service["script"] = garbage
    assert probe_health(raw_service["port"], timeout=2) == "not-spyglass"


def test_probe_health_connection_closed_mid_body_is_not_spyglass(raw_service) -> None:
    """A reply that promises more body than it sends must not crash the probe."""
    def truncated(conn):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n{\"version\": ")
        conn.close()

    raw_service["script"] = truncated
    assert probe_health(raw_service["port"], timeout=2) == "not-spyglass"


def test_probe_health_connection_dropped_without_a_reply_is_not_spyglass(raw_service) -> None:
    """Accepting and closing at once is something other than a healthy Spyglass."""
    raw_service["script"] = lambda conn: conn.close()
    assert probe_health(raw_service["port"], timeout=2) == "not-spyglass"


def test_probe_health_a_service_that_never_answers_is_not_spyglass(raw_service) -> None:
    """A hung or busy service accepted the connection, so the port is taken, not free."""
    raw_service["script"] = lambda conn: threading.Event().wait(1.5)
    assert probe_health(raw_service["port"], timeout=0.3) == "not-spyglass"


@pytest.fixture
def redirect(monkeypatch):
    """Call redirect_output, then close the log files and restore sys.stdout and sys.stderr.

    The streams are kept here because pytest's own capture swaps sys.stdout back between the
    test and its fixtures' teardown, which would otherwise leave the log files unclosed.
    """
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    opened = []

    def run(data_dir, **kwargs):
        redirect_output(data_dir, **kwargs)
        opened.extend((sys.stdout, sys.stderr))

    yield run
    for stream in opened:
        stream.close()


def test_redirect_output_appends_to_the_logs(tmp_path, redirect) -> None:
    """Output lands in service.log and errors in service.err.log, across restarts."""
    (tmp_path / "service.log").write_text("earlier\n", encoding="utf-8")
    redirect(tmp_path)
    print("hello")
    print("oops", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    assert (tmp_path / "service.log").read_text(encoding="utf-8") == "earlier\nhello\n"
    assert (tmp_path / "service.err.log").read_text(encoding="utf-8") == "oops\n"


def test_redirect_output_rotates_large_logs(tmp_path, redirect) -> None:
    """A log over the limit moves to .1 (replacing an older .1) and a fresh file starts."""
    (tmp_path / "service.log").write_text("x" * 50, encoding="utf-8")
    (tmp_path / "service.err.log").write_text("y" * 50, encoding="utf-8")
    (tmp_path / "service.log.1").write_text("stale", encoding="utf-8")
    redirect(tmp_path, limit_bytes=10)
    assert (tmp_path / "service.log.1").read_text(encoding="utf-8") == "x" * 50
    assert (tmp_path / "service.err.log.1").read_text(encoding="utf-8") == "y" * 50
    assert (tmp_path / "service.log").read_text(encoding="utf-8") == ""
    assert (tmp_path / "service.err.log").read_text(encoding="utf-8") == ""


def test_redirect_output_keeps_a_small_log(tmp_path, redirect) -> None:
    """A log under the limit is not rotated."""
    (tmp_path / "service.log").write_text("small", encoding="utf-8")
    redirect(tmp_path, limit_bytes=10)
    assert not (tmp_path / "service.log.1").exists()


def test_single_instance_lock_is_per_data_folder_and_lasts_while_the_holder_lives(tmp_path) -> None:
    """The lock sits on desktop.lock; a live holder keeps it however old it is."""
    first = single_instance_lock(tmp_path)
    assert first.path == tmp_path / "desktop.lock"
    assert first.acquire() is True
    other = CycleFileLock(first.path, pid_alive=lambda _pid: True, pid=999_999_998, max_age=None)
    assert other.acquire() is False
    first.release()
    assert other.acquire() is True
    other.release()


def _old_folder(folder: Path) -> Path:
    """A data folder holding a database from before the redesign."""
    folder.mkdir()
    conn = sqlite3.connect(folder / "spyglass.db")
    conn.execute('CREATE TABLE "items" (id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()
    return folder


def test_check_data_dir_command_returns_the_verdict(tmp_path, capsys) -> None:
    """An old folder gives exit code 3 and prints why."""
    old = _old_folder(tmp_path / "old")
    assert main(["--check-data-dir", str(old)]) == 3
    assert "older Spyglass" in capsys.readouterr().out


def test_check_data_dir_command_accepts_a_folder_that_does_not_exist_yet(tmp_path, capsys) -> None:
    """The installer creates the folder after the check, so a missing one is fine."""
    assert main(["--check-data-dir", str(tmp_path / "new")]) == 0
    assert capsys.readouterr().out == ""


def test_check_data_dir_command_refuses_a_newer_folder(tmp_path, capsys) -> None:
    """A folder last used by a newer Spyglass gives exit code 4."""
    record_data_version(tmp_path, "99.0.0")
    assert main(["--check-data-dir", str(tmp_path)]) == 4
    assert "99.0.0" in capsys.readouterr().out


def test_redirect_output_keeps_appending_when_rotation_fails(tmp_path, redirect, monkeypatch) -> None:
    """Another process holding the log open must not stop the launcher from starting."""
    (tmp_path / "service.log").write_text("x" * 50, encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise PermissionError("held open by another process")

    monkeypatch.setattr(os, "replace", refuse)
    redirect(tmp_path, limit_bytes=10)
    print("still logging")
    sys.stdout.flush()
    assert (tmp_path / "service.log").read_text(encoding="utf-8") == "x" * 50 + "still logging\n"
    assert not (tmp_path / "service.log.1").exists()


def test_redirect_output_falls_back_to_devnull_when_a_log_cannot_be_opened(
        tmp_path, redirect) -> None:
    """A log that cannot be opened drops its output; the other log still works."""
    (tmp_path / "service.log").mkdir()  # opening a folder for appending fails
    redirect(tmp_path)
    print("lost")
    print("kept", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    assert (tmp_path / "service.err.log").read_text(encoding="utf-8") == "kept\n"
