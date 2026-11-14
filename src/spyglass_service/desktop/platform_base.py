"""What the desktop app needs from the operating system, and the adapter for this machine.

The tray app, the Settings routes and the launcher talk to `DesktopPlatform` only. Windows is
the sole adapter today; `default_platform` returns None elsewhere so callers can degrade (for
example, hide the "start with Windows" switch) instead of failing.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Browser:
    """An installed browser: a stable id, a display name, its executable and its extensions page."""

    id: str
    name: str
    exe: Path
    extensions_url: str


class DesktopPlatform(Protocol):
    """The operating-system operations the desktop app uses."""

    def autostart_enabled(self) -> bool:
        """Whether Spyglass is registered to start when the user signs in."""
        ...

    def set_autostart(self, enabled: bool) -> None:
        """Register or remove the start-at-sign-in entry."""
        ...

    def installed_browsers(self) -> list[Browser]:
        """The supported browsers that are installed on this machine."""
        ...

    def open_extensions_page(self, browser_id: str) -> None:
        """Open a browser's extensions page; raises KeyError for an unknown or missing browser."""
        ...

    def show_message(self, title: str, text: str) -> None:
        """Show a blocking message box to the user."""
        ...

    def process_started_at(self, pid: int) -> datetime | None:
        """When the process with this id was created (aware UTC); None if it cannot be read."""
        ...

    def boot_time(self) -> datetime | None:
        """When the machine last started (aware UTC); None when this system cannot tell."""
        return None


def no_window_flags() -> int:
    """The `creationflags` that start a console program without a console window.

    The desktop app runs under pythonw.exe, which has no console, so Windows gives every console
    child (Claude's command line, yt-transcribe, taskkill) a window of its own unless asked not
    to. Other systems have no such windows, and subprocess refuses non-zero flags there.
    """
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0


def default_platform() -> DesktopPlatform | None:
    """The adapter for this machine: a `WindowsPlatform` on Windows, None on any other system."""
    if sys.platform != "win32":
        return None
    # Imported here so that no Windows-only module loads on other systems.
    from spyglass_service.desktop.platform_windows import WindowsPlatform

    return WindowsPlatform()
