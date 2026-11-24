"""The desktop entry's last line of defence: an unexpected error during a start is written to a
crash log beside desktop.json and shown in a message box, because under pythonw nothing else is
visible. Nothing here starts a real launcher, tray or message box."""

from pathlib import Path

import pytest

import spyglass_service.desktop.launcher as launcher_mod
from spyglass_service.desktop import __main__ as desktop_main


class FakePlatform:
    """Records message boxes."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def show_message(self, title: str, text: str) -> None:
        self.messages.append((title, text))


class BrokenLauncher:
    """A launcher whose run() fails the way a read-only data folder makes the lock fail."""

    def run(self, background: bool = False, restart: bool = False) -> int:
        raise PermissionError("the data folder is read-only")


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(desktop_main, "default_platform", lambda: fake)
    monkeypatch.setattr(launcher_mod, "Launcher", BrokenLauncher)
    return fake


def test_an_error_inside_run_is_logged_and_shown(platform, tmp_path: Path, monkeypatch) -> None:
    """The traceback goes to launcher-crash.log in desktop.json's folder (created if missing),
    the user is told where it is, and the exit code is not zero."""
    folder = tmp_path / "Spyglass"
    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(folder / "desktop.json"))
    assert desktop_main.main([]) != 0
    log = folder / "launcher-crash.log"
    text = log.read_text(encoding="utf-8")
    assert "PermissionError" in text and "the data folder is read-only" in text
    assert platform.messages == [
        ("Spyglass", f"Spyglass could not start. Details are in {log}.")]


def test_a_crash_log_that_cannot_be_written_still_shows_the_message(
        platform, tmp_path: Path, monkeypatch) -> None:
    """A folder that cannot be created (here a file stands in its place) does not hide the error.
    With no log to point at, the message names the error itself instead."""
    blocker = tmp_path / "Spyglass"
    blocker.write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(blocker / "desktop.json"))
    assert desktop_main.main(["--background"]) != 0
    assert platform.messages == [
        ("Spyglass", "Spyglass could not start: PermissionError: the data folder is read-only")]


def test_only_the_first_line_of_a_long_error_is_shown(platform, tmp_path: Path, monkeypatch) -> None:
    class Wordy:
        def run(self, background: bool = False, restart: bool = False) -> int:
            raise RuntimeError("first line\nsecond line\nthird line")

    monkeypatch.setattr(launcher_mod, "Launcher", Wordy)
    monkeypatch.setattr(desktop_main, "_write_crash_log", lambda path, details: False)
    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(tmp_path / "desktop.json"))
    assert desktop_main.main([]) != 0
    assert platform.messages == [("Spyglass", "Spyglass could not start: RuntimeError: first line")]


def test_the_folder_check_is_not_guarded(platform, tmp_path: Path) -> None:
    """The installer runs --check-data-dir and reads its exit code and output; it never sees a
    message box from it."""
    assert desktop_main.main(["--check-data-dir", str(tmp_path / "new")]) == 0
    assert platform.messages == []
