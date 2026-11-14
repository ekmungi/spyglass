"""The tray icon of the desktop app: Open Spyglass, Start with Windows, and Quit Spyglass.

The launcher owns what each item does; this module only builds the pystray icon around the
callbacks it is given, so it can be tested without showing anything.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

# The icon the installer ships, made from the extension's icon; a drawn one stands in without it.
ICON_PATH = Path(__file__).resolve().parents[3] / "installer" / "spyglass.ico"
# Side of the drawn placeholder, in pixels; Windows scales it to the tray's size.
PLACEHOLDER_SIZE = 64
# The Windows message for a right-button release on the icon, which opens the menu.
_WM_RBUTTONUP = 0x0205


def _icon_image() -> Image.Image:
    """The installer's icon when present, otherwise a drawn lens on a dark disc."""
    if ICON_PATH.is_file():
        try:
            with Image.open(ICON_PATH) as image:
                image.load()
                return image.copy()
        except OSError:
            pass  # a damaged icon file must not stop the app; draw the placeholder instead
    size = PLACEHOLDER_SIZE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size - 3, size - 3), fill=(28, 46, 74, 255))
    draw.ellipse((14, 14, 42, 42), outline=(235, 240, 248, 255), width=5)
    draw.line((38, 38, 52, 52), fill=(235, 240, 248, 255), width=7)
    return image


def _icon_class() -> type:
    """pystray's icon class, refreshed before its menu opens where the backend allows it.

    pystray's Windows backend builds the menu once and again only after a menu click, so a
    switch changed in Settings or in Task Manager would show stale in the tray. Rebuilding on
    the right-button release keeps the check item reading the start-up entry each time the menu
    opens. Backends without the Windows handler get pystray's class unchanged.
    """
    base = pystray.Icon
    if not hasattr(base, "_on_notify"):
        return base

    class RefreshingIcon(base):  # type: ignore[misc, valid-type]
        """pystray's Windows icon, with the menu rebuilt just before it opens."""

        def _on_notify(self, wparam, lparam):
            if lparam == _WM_RBUTTONUP:
                self.update_menu()
            super()._on_notify(wparam, lparam)

    return RefreshingIcon


def build_tray(on_open: Callable[[], None], on_quit: Callable[[], None],
               autostart: Callable[[], bool], toggle_autostart: Callable[[], None],
               version: str) -> pystray.Icon:
    """Build (not run) the tray icon.

    on_open: opens the interface; it is the default item, so a left click runs it too.
    on_quit: the launcher's one stop path. autostart: reads the start-up entry. toggle_autostart:
    flips it. version: shown in the tooltip as "Spyglass <version>".
    """
    menu = pystray.Menu(
        pystray.MenuItem("Open Spyglass", lambda: on_open(), default=True),
        pystray.MenuItem("Start with Windows", lambda: toggle_autostart(),
                         checked=lambda _: autostart()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Spyglass", lambda: on_quit()),
    )
    return _icon_class()("spyglass", icon=_icon_image(), title=f"Spyglass {version}", menu=menu)
