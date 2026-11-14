"""Runs the tray loop on the main thread and lets any thread close it, early or late.

pystray ignores stop() until its loop is live (it marks itself running inside run()), so a close
that comes early, such as a service crash during start, would be lost and leave an icon for a
Spyglass that is gone. The runner remembers such a close and applies it from pystray's setup
callback, which runs once the loop is live.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TrayLike(Protocol):
    """What the runner needs from pystray.Icon."""

    visible: bool

    def run(self, setup: Callable[[Any], None] | None = None) -> None:
        """Run the tray loop on this thread until stop()."""
        ...

    def stop(self) -> None:
        """End the tray loop; pystray ignores it until the loop is live."""
        ...


class TrayRunner:
    """One tray loop: run() on the main thread, close() from any thread, at any time."""

    def __init__(self) -> None:
        """Start with no tray, not live, and no close asked for."""
        self._guard = threading.Lock()
        self._tray: TrayLike | None = None
        self._live = False
        self._close_asked = False
        self._closed = threading.Event()

    def run(self, tray: TrayLike) -> None:
        """Run `tray` on this thread until it is closed; return at once if a close came first."""
        try:
            with self._guard:
                self._tray = tray
                closed_already = self._close_asked
            if not closed_already:
                tray.run(setup=self._setup)
        finally:
            self._closed.set()

    def close(self) -> None:
        """End the loop now if it is live, otherwise as soon as it is (or keep it from starting)."""
        with self._guard:
            self._close_asked = True
            tray = self._tray if self._live else None
        if tray is None:
            return
        try:
            tray.stop()
        except Exception:
            logger.exception("The tray icon could not be closed")

    def wait_closed(self, timeout: float) -> bool:
        """Block until run() has returned; False if `timeout` passed first."""
        return self._closed.wait(timeout)

    def _setup(self, icon: TrayLike) -> None:
        """pystray's setup callback, run once the loop is live: apply a close that came before
        the loop could take it, otherwise show the icon.

        The loop is marked live first, so close() works whatever happens next. An icon that
        cannot be shown ends the loop, and the launcher then stops the service, so the process
        never lingers with no icon to quit it from.
        """
        with self._guard:
            self._live = True
            close_now = self._close_asked
        if close_now:
            icon.stop()
            return
        try:
            icon.visible = True
        except Exception:
            logger.exception("The tray icon could not be shown")
            icon.stop()
