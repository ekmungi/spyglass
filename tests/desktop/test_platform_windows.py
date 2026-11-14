"""The Windows platform module, driven through a fake registry and a fake launcher."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spyglass_service.desktop import platform_base
from spyglass_service.desktop.platform_base import Browser, default_platform
from spyglass_service.desktop.platform_windows import (
    RUN_KEY,
    RUN_VALUE,
    WindowsPlatform,
    autostart_command,
)


class FakeRegistry:
    """A dict-backed stand-in for the HKCU registry."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get(self, key: str, name: str) -> str | None:
        return self.values.get((key, name))

    def set(self, key: str, name: str, value: str) -> None:
        self.values[(key, name)] = value

    def delete(self, key: str, name: str) -> None:
        self.values.pop((key, name), None)


def _exe(tmp_path: Path, *parts: str) -> Path:
    path = tmp_path.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_autostart_round_trip_writes_and_removes_the_run_value(tmp_path: Path) -> None:
    registry = FakeRegistry()
    pythonw = tmp_path / "pythonw.exe"
    platform = WindowsPlatform(registry=registry, pythonw=pythonw)

    assert platform.autostart_enabled() is False

    platform.set_autostart(True)
    assert platform.autostart_enabled() is True
    assert registry.values[(RUN_KEY, RUN_VALUE)] == autostart_command(pythonw)

    platform.set_autostart(False)
    assert platform.autostart_enabled() is False
    assert (RUN_KEY, RUN_VALUE) not in registry.values


def test_disabling_autostart_when_absent_is_harmless(tmp_path: Path) -> None:
    platform = WindowsPlatform(registry=FakeRegistry(), pythonw=tmp_path / "pythonw.exe")
    platform.set_autostart(False)
    assert platform.autostart_enabled() is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path rendering")
def test_autostart_command_quotes_paths_with_spaces() -> None:
    assert autostart_command(
        Path("C:/Users/Ann Smith/Spyglass/.venv/Scripts/pythonw.exe")
    ) == (
        '"C:\\Users\\Ann Smith\\Spyglass\\.venv\\Scripts\\pythonw.exe"'
        " -m spyglass_service.desktop --background"
    )


def test_autostart_command_wraps_the_interpreter_in_quotes() -> None:
    command = autostart_command(Path("pythonw.exe"))
    assert command.startswith('"')
    assert command.endswith('" -m spyglass_service.desktop --background')


def test_installed_browsers_lists_only_existing_executables(tmp_path: Path) -> None:
    chrome = _exe(tmp_path, "chrome", "chrome.exe")
    vivaldi = _exe(tmp_path, "vivaldi-user", "vivaldi.exe")
    candidates = {
        "chrome": [tmp_path / "missing" / "chrome.exe", chrome],
        "edge": [tmp_path / "missing" / "msedge.exe"],
        "vivaldi": [vivaldi],
        "brave": [],
    }
    platform = WindowsPlatform(registry=FakeRegistry(), candidates=candidates)

    browsers = platform.installed_browsers()

    assert [b.id for b in browsers] == ["chrome", "vivaldi"]
    assert browsers[0] == Browser(
        id="chrome", name="Google Chrome", exe=chrome, extensions_url="chrome://extensions"
    )
    assert browsers[1].exe == vivaldi
    assert browsers[1].extensions_url == "vivaldi://extensions"


def test_open_extensions_page_launches_the_browser_with_its_address(tmp_path: Path) -> None:
    vivaldi = _exe(tmp_path, "vivaldi", "vivaldi.exe")
    launched: list[list[str]] = []
    platform = WindowsPlatform(
        registry=FakeRegistry(),
        launch=lambda args: launched.append(args),
        candidates={"vivaldi": [vivaldi]},
    )

    platform.open_extensions_page("vivaldi")

    assert launched == [[str(vivaldi), "vivaldi://extensions"]]


def test_open_extensions_page_rejects_an_unknown_browser(tmp_path: Path) -> None:
    launched: list[list[str]] = []
    platform = WindowsPlatform(
        registry=FakeRegistry(),
        launch=lambda args: launched.append(args),
        candidates={"chrome": [tmp_path / "missing" / "chrome.exe"]},
    )

    with pytest.raises(KeyError):
        platform.open_extensions_page("netscape")
    with pytest.raises(KeyError):
        platform.open_extensions_page("chrome")  # known, but not installed
    assert launched == []


def test_default_platform_is_none_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_base.sys, "platform", "linux")
    assert default_platform() is None


def test_no_window_flags_is_zero_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Other systems have no console windows to hide, and subprocess refuses non-zero flags."""
    monkeypatch.setattr(platform_base.sys, "platform", "linux")
    assert platform_base.no_window_flags() == 0


@pytest.mark.skipif(sys.platform != "win32", reason="the flag exists only on Windows")
def test_no_window_flags_hides_the_console_on_windows() -> None:
    """Under pythonw a console program started without this flag opens a window."""
    import subprocess

    assert platform_base.no_window_flags() == subprocess.CREATE_NO_WINDOW


def test_default_launcher_starts_the_browser_without_a_console(monkeypatch, tmp_path: Path) -> None:
    """The extensions page opens through one helper that passes the no-window flag."""
    from spyglass_service.desktop import platform_windows

    started: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(platform_windows.subprocess, "Popen",
                        lambda args, **kwargs: started.append((args, kwargs)))
    edge = _exe(tmp_path, "edge", "msedge.exe")
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={"edge": [edge]})
    platform.open_extensions_page("edge")
    assert started == [([str(edge), "edge://extensions"],
                        {"creationflags": platform_base.no_window_flags()})]


@pytest.mark.skipif(sys.platform != "win32", reason="MessageBoxW exists only on Windows")
def test_show_message_comes_to_the_front(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under pythonw a plain box can open behind other windows; it must come to the front."""
    import ctypes

    shown: list[tuple] = []
    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda *args: shown.append(args))
    WindowsPlatform(registry=FakeRegistry(), candidates={}).show_message("Spyglass", "Hello")
    information, set_foreground, topmost = 0x40, 0x10000, 0x40000
    assert shown == [(None, "Hello", "Spyglass", information | set_foreground | topmost)]
