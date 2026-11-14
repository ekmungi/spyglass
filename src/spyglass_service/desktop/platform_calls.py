"""Calls into the desktop platform that never raise.

The launcher and the start-up crash guard both talk to the operating system at moments when a
failure must not stop them (deciding about a lock, showing why Spyglass cannot start). Each call
here logs a failure and answers with a safe default instead; with no platform at all (a system
other than Windows) the answers are the same defaults and messages go to stderr.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from spyglass_service.desktop.platform_base import DesktopPlatform

logger = logging.getLogger(__name__)


class PlatformCalls:
    """A `DesktopPlatform` (or None) behind calls that log their failures and never raise."""

    def __init__(self, platform: DesktopPlatform | None) -> None:
        """Wrap `platform`; None means this system has no adapter."""
        self._platform = platform

    def process_started_at(self, pid: int) -> datetime | None:
        """When process `pid` was created, for the lock's reused-pid check; None if unknown."""
        if self._platform is None:
            return None
        try:
            return self._platform.process_started_at(pid)
        except Exception:
            logger.exception("Could not read when process %s started", pid)
            return None

    def boot_time(self) -> datetime | None:
        """When the machine last started, for the lock's before-the-restart check; None if unknown."""
        if self._platform is None:
            return None
        try:
            return self._platform.boot_time()
        except Exception:
            logger.exception("Could not read when the machine started")
            return None

    def autostart_enabled(self) -> bool:
        """Whether the start-up entry exists; False when it cannot be read."""
        if self._platform is None:
            return False
        try:
            return self._platform.autostart_enabled()
        except Exception:
            logger.exception("Could not read the start-with-Windows entry")
            return False

    def toggle_autostart(self) -> None:
        """Flip the start-up entry from what is actually there, not from what the menu showed."""
        if self._platform is None:
            return
        try:
            self._platform.set_autostart(not self._platform.autostart_enabled())
        except Exception:
            logger.exception("Could not change the start-with-Windows entry")

    def show(self, title: str, text: str) -> None:
        """Tell the user something: a message box, or stderr when there is none or it fails."""
        if self._platform is not None:
            try:
                self._platform.show_message(title, text)
                return
            except Exception:
                logger.exception("Could not show a message box")
        try:
            print(text, file=sys.stderr)
        except (AttributeError, OSError, ValueError):
            pass  # pythonw has no stderr; nothing more can be done
