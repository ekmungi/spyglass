"""The Claude Code connector that setup adds: added when absent, never replacing a foreign one."""

import json
from pathlib import Path

from spyglass_service.desktop import connector
from spyglass_service.desktop.connector import add_connector, connector_url, remove_connector


class FakeRun:
    """Records each command and answers with the exit code given for its first argument word."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, args: list[str], env: dict | None = None) -> tuple[int, str]:
        self.calls.append(list(args))
        return self.code, ""


def _claude_config(home: Path, servers: dict) -> None:
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_url_points_at_this_computer() -> None:
    assert connector_url(7777) == "http://127.0.0.1:7777/mcp/"


def test_adds_the_connector_when_none_exists(tmp_path: Path) -> None:
    run = FakeRun()
    _claude_config(tmp_path, {})
    assert add_connector("claude.exe", 7777, home=tmp_path, run=run) == "added"
    assert run.calls == [["claude.exe", "mcp", "add", "--scope", "user", "--transport", "http",
                          "spyglass", "http://127.0.0.1:7777/mcp/"]]


def test_leaves_its_own_connector_alone(tmp_path: Path) -> None:
    """An entry that already points at this Spyglass (localhost or 127.0.0.1) needs nothing."""
    run = FakeRun()
    _claude_config(tmp_path, {"spyglass": {"type": "http", "url": "http://localhost:7777/mcp"}})
    assert add_connector("claude.exe", 7777, home=tmp_path, run=run) == "present"
    assert run.calls == []


def test_never_replaces_a_connector_that_points_elsewhere(tmp_path: Path) -> None:
    run = FakeRun()
    _claude_config(tmp_path, {"spyglass": {"type": "http", "url": "http://127.0.0.1:9999/mcp/"}})
    assert add_connector("claude.exe", 7777, home=tmp_path, run=run) == "foreign"
    assert run.calls == []


def test_a_failed_add_is_reported(tmp_path: Path) -> None:
    assert add_connector("claude.exe", 7777, home=tmp_path, run=FakeRun(code=1)) == "failed"


def test_without_claude_nothing_is_run(tmp_path: Path) -> None:
    run = FakeRun()
    assert add_connector(None, 7777, home=tmp_path, run=run) == "no-claude"
    assert remove_connector(None, 7777, home=tmp_path, run=run) == "no-claude"
    assert run.calls == []


def test_removes_only_its_own_connector(tmp_path: Path) -> None:
    run = FakeRun()
    _claude_config(tmp_path, {"spyglass": {"type": "http", "url": "http://127.0.0.1:7777/mcp/"}})
    assert remove_connector("claude.exe", 7777, home=tmp_path, run=run) == "removed"
    assert run.calls == [["claude.exe", "mcp", "remove", "--scope", "user", "spyglass"]]


def test_does_not_remove_a_connector_that_now_points_elsewhere(tmp_path: Path) -> None:
    run = FakeRun()
    _claude_config(tmp_path, {"spyglass": {"type": "http", "url": "https://example.com/mcp"}})
    assert remove_connector("claude.exe", 7777, home=tmp_path, run=run) == "foreign"
    assert run.calls == []


def test_unreadable_claude_config_counts_as_no_connector(tmp_path: Path) -> None:
    (tmp_path / ".claude.json").write_text("{not json", encoding="utf-8")
    assert connector.registered_url(tmp_path) is None


def test_claude_config_dir_variable_is_honoured(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    _claude_config(other, {"spyglass": {"url": "http://127.0.0.1:7777/mcp/"}})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(other))
    assert connector.registered_url(tmp_path) == "http://127.0.0.1:7777/mcp/"


def test_finds_claude_in_the_native_installer_folder(tmp_path: Path) -> None:
    exe = tmp_path / ".local" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert connector.find_claude(tmp_path, which=lambda _name: None) == str(exe)


def test_finds_no_claude_when_there_is_none(tmp_path: Path) -> None:
    assert connector.find_claude(tmp_path, which=lambda _name: None) is None
