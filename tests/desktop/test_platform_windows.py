"""The Windows platform module, driven through a fake registry and a fake launcher."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spyglass_service.desktop import platform_base
from spyglass_service.desktop.platform_base import UNSUPPORTED, Browser, default_platform
from spyglass_service.desktop.platform_windows import (
    LAUNCHER_NAME,
    RUN_KEY,
    RUN_VALUE,
    WindowsPlatform,
    autostart_command,
    launcher_path,
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


def _installed(tmp_path: Path) -> tuple[Path, Path]:
    """An install folder laid out as the installer leaves it: the launcher beside the venv."""
    pythonw = _exe(tmp_path, "Spyglass", ".venv", "Scripts", "pythonw.exe")
    launcher = _exe(tmp_path, "Spyglass", LAUNCHER_NAME)
    return pythonw, launcher


def test_launcher_path_finds_the_program_beside_the_venv(tmp_path: Path) -> None:
    pythonw, launcher = _installed(tmp_path)
    assert launcher_path(pythonw) == launcher


def test_launcher_path_is_none_in_a_checkout(tmp_path: Path) -> None:
    """A repository clone has a .venv but no Spyglass.exe beside it."""
    pythonw = _exe(tmp_path, "spyglass", ".venv", "Scripts", "pythonw.exe")
    assert launcher_path(pythonw) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path rendering")
def test_autostart_command_starts_the_launcher_in_the_background() -> None:
    command = autostart_command(Path("pythonw.exe"), Path("C:/Program Files/Spyglass/Spyglass.exe"))
    assert command == '"C:\\Program Files\\Spyglass\\Spyglass.exe" --background'


def test_switching_on_writes_the_launcher_when_installed(tmp_path: Path) -> None:
    """The installed app writes the same start-up entry as the installer: Spyglass.exe."""
    pythonw, launcher = _installed(tmp_path)
    registry = FakeRegistry()
    WindowsPlatform(registry=registry, pythonw=pythonw).set_autostart(True)
    assert registry.values[(RUN_KEY, RUN_VALUE)] == f'"{launcher}" --background'


def test_switching_on_writes_python_from_a_checkout(tmp_path: Path) -> None:
    """Run from a clone, with no launcher, the entry starts Python as before."""
    pythonw = _exe(tmp_path, "spyglass", ".venv", "Scripts", "pythonw.exe")
    registry = FakeRegistry()
    WindowsPlatform(registry=registry, pythonw=pythonw).set_autostart(True)
    assert registry.values[(RUN_KEY, RUN_VALUE)] == autostart_command(pythonw)


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


def test_opera_is_found_where_its_own_installer_puts_it(tmp_path: Path, monkeypatch) -> None:
    """Opera installs per user under Programs, or for all users straight under Program Files."""
    from spyglass_service.desktop.platform_windows import _default_candidates

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    found = _default_candidates()["opera"]
    assert tmp_path / "local" / "Programs" / "Opera" / "opera.exe" in found
    assert tmp_path / "pf" / "Opera" / "opera.exe" in found


def test_opera_opens_its_own_extensions_page(tmp_path: Path) -> None:
    opera = _exe(tmp_path, "opera", "opera.exe")
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={"opera": [opera]})
    browsers = platform.installed_browsers()
    assert [(b.id, b.name, b.extensions_url) for b in browsers] == [
        ("opera", "Opera", "opera://extensions")]


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


def test_process_started_at_converts_the_creation_time() -> None:
    """Windows counts process times in 100 ns steps from 1601; this value is the Unix epoch."""
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={},
                               process_times=lambda pid: 116_444_736_000_000_000)
    assert platform.process_started_at(4242) == datetime(1970, 1, 1, tzinfo=UTC)


def test_process_started_at_is_none_when_the_process_cannot_be_read() -> None:
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={}, process_times=lambda pid: None)
    assert platform.process_started_at(4242) is None


def test_boot_time_is_now_minus_the_time_since_start() -> None:
    """Windows counts milliseconds since the machine started; the boot is that long ago."""
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={},
                               uptime_ms=lambda: 3_600_000)
    expected = datetime.now(UTC) - timedelta(hours=1)
    booted = platform.boot_time()
    assert booted is not None and booted.tzinfo is not None
    assert abs(booted - expected) < timedelta(seconds=5)


@pytest.mark.skipif(sys.platform != "win32", reason="GetTickCount64 exists only on Windows")
def test_boot_time_reads_the_real_clock() -> None:
    """The machine started before this process did, and in the past."""
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={})
    booted = platform.boot_time()
    started = platform.process_started_at(os.getpid())
    assert booted is not None and started is not None
    assert booted <= started + timedelta(seconds=2)
    assert booted < datetime.now(UTC)


@pytest.mark.skipif(sys.platform != "win32", reason="GetProcessTimes exists only on Windows")
def test_process_started_at_reads_a_real_process() -> None:
    """This process started in the past (aware UTC); a free pid has no start time."""
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={})
    started = platform.process_started_at(os.getpid())
    now = datetime.now(UTC)
    assert started is not None and started.tzinfo is not None
    assert now - timedelta(days=1) < started <= now
    assert platform.process_started_at(2**31 - 3) is None
    assert platform.process_started_at(0) is None


def _platform_with_lock(lock_byte) -> WindowsPlatform:
    return WindowsPlatform(registry=FakeRegistry(), candidates={}, lock_byte=lock_byte)


def test_try_hold_instance_returns_a_hold_that_releases(tmp_path: Path) -> None:
    """The instance file is created if missing, its first byte is locked, and the hold keeps the
    file open until it is released; the file itself is never deleted."""
    locked: list[int] = []
    path = tmp_path / "desktop.instance"
    hold = _platform_with_lock(locked.append).try_hold_instance(path)
    assert hold is not None and hold is not UNSUPPORTED
    assert len(locked) == 1 and path.exists()
    hold.release()
    hold.release()  # a second release is harmless
    path.unlink()  # the file is closed again (Windows refuses to delete an open file)


@pytest.mark.parametrize("code", [errno.EACCES, errno.EDEADLK])
def test_try_hold_instance_reports_busy_when_the_byte_is_locked(tmp_path: Path, code: int) -> None:
    def busy(fd: int) -> None:
        raise OSError(code, "the region is locked")

    path = tmp_path / "desktop.instance"
    assert _platform_with_lock(busy).try_hold_instance(path) is None
    path.unlink()  # the file was closed after the failed attempt


def test_try_hold_instance_raises_any_other_error(tmp_path: Path) -> None:
    def broken(fd: int) -> None:
        raise OSError(errno.EIO, "the disk failed")

    path = tmp_path / "desktop.instance"
    with pytest.raises(OSError, match="the disk failed"):
        _platform_with_lock(broken).try_hold_instance(path)
    path.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="byte-range locks are Windows-only here")
def test_two_holds_on_one_instance_file_exclude_each_other(tmp_path: Path) -> None:
    platform = WindowsPlatform(registry=FakeRegistry(), candidates={})
    path = tmp_path / "desktop.instance"
    first = platform.try_hold_instance(path)
    assert first is not None and first is not UNSUPPORTED
    try:
        assert platform.try_hold_instance(path) is None
    finally:
        first.release()
    again = platform.try_hold_instance(path)
    assert again is not None and again is not UNSUPPORTED
    again.release()


_HOLDER = """
import os, sys, time
from pathlib import Path
from spyglass_service.desktop.platform_windows import WindowsPlatform
hold = WindowsPlatform().try_hold_instance(Path(sys.argv[1]))
print("busy" if hold is None else "held", os.getpid(), flush=True)
time.sleep(60)
"""

# How long the test allows the kernel to drop a killed holder's lock. Termination is
# asynchronous to the kill call and there is no process handle to wait on, so the test polls.
_RELEASE_WAIT_S = 5.0


def _end_process(pid: int) -> None:
    """End `pid` without running any of its code (TerminateProcess on Windows); ignore a pid
    that has already gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="byte-range locks are Windows-only here")
def test_the_kernel_releases_the_hold_when_its_process_is_killed(tmp_path: Path) -> None:
    """Windows ends the launcher at sign-out or shutdown without running any of its code. The
    kernel still drops the lock, so the next start owns the instance within moments."""
    path = tmp_path / "desktop.instance"
    child = subprocess.Popen(  # noqa: S603 -- this interpreter, a fixed script
        [sys.executable, "-c", _HOLDER, str(path)], stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
    holder_pid = None
    try:
        assert child.stdout is not None
        state, pid_text = child.stdout.readline().split()
        assert state == "held"
        # A virtual environment's python.exe is a small launcher that runs the real interpreter
        # as its own child, so the lock belongs to the pid the script reports, not to `child`.
        holder_pid = int(pid_text)
        platform = WindowsPlatform(registry=FakeRegistry(), candidates={})
        assert platform.try_hold_instance(path) is None
        _end_process(holder_pid)
        deadline = time.monotonic() + _RELEASE_WAIT_S
        hold = platform.try_hold_instance(path)
        while hold is None and time.monotonic() < deadline:
            time.sleep(0.05)
            hold = platform.try_hold_instance(path)
        assert hold is not None and hold is not UNSUPPORTED
        hold.release()
    finally:
        if holder_pid is not None:
            _end_process(holder_pid)
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()
