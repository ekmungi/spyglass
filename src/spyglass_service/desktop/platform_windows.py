"""The Windows adapter: the sign-in start-up entry, installed browsers and message boxes.

Every Windows-only call (`winreg`, `ctypes.windll`) is imported inside the method that needs
it, so this module imports on any system and tests can inject a fake registry and launcher.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from spyglass_service.desktop.platform_base import Browser, no_window_flags

# The per-user key Windows reads at sign-in; a value here starts a program without admin rights.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# The name Spyglass gives its value, so it can find and remove only its own entry.
RUN_VALUE = "Spyglass"

# MessageBoxW style: an information icon with a single OK button, brought to the front and kept
# above other windows. A pythonw process owns no window, so without the last two flags Windows
# may open the box behind whatever the user is looking at, and the start seems to do nothing.
_MB_OK_INFORMATION = 0x40
_MB_SETFOREGROUND = 0x10000
_MB_TOPMOST = 0x40000
_MB_STYLE = _MB_OK_INFORMATION | _MB_SETFOREGROUND | _MB_TOPMOST

# (id, display name, extensions address, executable path under an Application root)
_BROWSERS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("chrome", "Google Chrome", "chrome://extensions", ("Google", "Chrome", "Application", "chrome.exe")),
    ("edge", "Microsoft Edge", "edge://extensions", ("Microsoft", "Edge", "Application", "msedge.exe")),
    ("vivaldi", "Vivaldi", "vivaldi://extensions", ("Vivaldi", "Application", "vivaldi.exe")),
    (
        "brave",
        "Brave",
        "brave://extensions",
        ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ),
)

# Per-machine (both bitnesses) and per-user install roots, in the order they are tried.
_ROOT_VARIABLES = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")


class RegistryAdapter(Protocol):
    """Reads and writes string values under HKEY_CURRENT_USER."""

    def get(self, key: str, name: str) -> str | None: ...

    def set(self, key: str, name: str, value: str) -> None: ...

    def delete(self, key: str, name: str) -> None: ...


class _WinregRegistry:
    """The real registry adapter; `winreg` is imported per call so other systems can import this."""

    def get(self, key: str, name: str) -> str | None:
        """The string value, or None when the key or the value does not exist."""
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        return str(value)

    def set(self, key: str, name: str, value: str) -> None:
        """Write a string value, creating the key when it is missing."""
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        """Remove a value; a missing key or value is not an error."""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE
            ) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            return


def autostart_command(pythonw: Path) -> str:
    """The command line stored in the Run key: the windowless interpreter, quoted for spaces."""
    return f'"{pythonw}" -m spyglass_service.desktop --background'


def _default_candidates() -> dict[str, list[Path]]:
    """Where each supported browser usually lives, from the machine's Application folders."""
    roots = [Path(os.environ[var]) for var in _ROOT_VARIABLES if os.environ.get(var)]
    return {
        browser_id: [root.joinpath(*parts) for root in roots]
        for browser_id, _name, _url, parts in _BROWSERS
    }


def _start_program(args: list[str]) -> subprocess.Popen:
    """Start a program and leave it running, with no console window under pythonw."""
    return subprocess.Popen(args, creationflags=no_window_flags())  # noqa: S603 -- no shell


class WindowsPlatform:
    """The `DesktopPlatform` for Windows; the registry, launcher and paths are injectable."""

    def __init__(
        self,
        registry: RegistryAdapter | None = None,
        launch: Callable[[list[str]], object] | None = None,
        candidates: dict[str, list[Path]] | None = None,
        pythonw: Path | None = None,
    ) -> None:
        """Build the adapter; each argument defaults to the real thing for this machine."""
        self._registry: RegistryAdapter = registry if registry is not None else _WinregRegistry()
        self._launch = launch if launch is not None else _start_program
        self._candidates = candidates if candidates is not None else _default_candidates()
        self._pythonw = pythonw or Path(sys.executable).with_name("pythonw.exe")

    def autostart_enabled(self) -> bool:
        """Whether a Spyglass value exists in the Run key."""
        return self._registry.get(RUN_KEY, RUN_VALUE) is not None

    def set_autostart(self, enabled: bool) -> None:
        """Write the Run value (replacing an older one) or remove it."""
        if enabled:
            self._registry.set(RUN_KEY, RUN_VALUE, autostart_command(self._pythonw))
        else:
            self._registry.delete(RUN_KEY, RUN_VALUE)

    def installed_browsers(self) -> list[Browser]:
        """The supported browsers whose first existing executable is found, in a fixed order."""
        found: list[Browser] = []
        for browser_id, name, url, _parts in _BROWSERS:
            exe = next((p for p in self._candidates.get(browser_id, []) if p.is_file()), None)
            if exe is not None:
                found.append(Browser(id=browser_id, name=name, exe=exe, extensions_url=url))
        return found

    def open_extensions_page(self, browser_id: str) -> None:
        """Start the browser on its extensions page; KeyError if it is unknown or not installed."""
        for browser in self.installed_browsers():
            if browser.id == browser_id:
                # The address is a separate argument, never run through a shell.
                self._launch([str(browser.exe), browser.extensions_url])
                return
        raise KeyError(browser_id)

    def show_message(self, title: str, text: str) -> None:
        """Show a blocking information box (used when no interface is up to tell the user)."""
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, _MB_STYLE)
