"""Tests for the tray icon's menu, tooltip and image, built on a fake pystray base class.

No icon is shown: pystray.Icon is replaced, so nothing registers a window or touches the
notification area.
"""

from pathlib import Path

import pytest

pystray = pytest.importorskip("pystray")
PIL_Image = pytest.importorskip("PIL.Image")

from spyglass_service.desktop import tray as tray_mod  # noqa: E402 -- after the skips

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205


class FakeIconBase:
    """Records what build_tray hands to pystray.Icon and how the menu refresh is ordered."""

    def __init__(self, name, icon=None, title=None, menu=None) -> None:
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.events: list[str] = []

    def update_menu(self) -> None:
        self.events.append("update_menu")

    def _on_notify(self, wparam, lparam) -> None:
        self.events.append(f"notify:{lparam}")


@pytest.fixture
def built(monkeypatch, tmp_path):
    """build_tray over the fake base, with recorders for every callback."""
    monkeypatch.setattr(pystray, "Icon", FakeIconBase)
    monkeypatch.setattr(tray_mod, "ICON_PATH", tmp_path / "missing.ico")
    calls: list[str] = []
    state = {"autostart": False}
    icon = tray_mod.build_tray(
        on_open=lambda: calls.append("open"),
        on_quit=lambda: calls.append("quit"),
        autostart=lambda: state["autostart"],
        toggle_autostart=lambda: calls.append("toggle"),
        version="0.41.0",
    )
    return icon, calls, state


def test_menu_has_open_start_with_windows_separator_and_quit(built) -> None:
    icon, _calls, _state = built
    items = list(icon.menu.items)
    assert [item.text for item in items] == [
        "Open Spyglass", "Start with Windows", pystray.Menu.SEPARATOR.text, "Quit Spyglass"]
    assert items[0].default is True
    assert not any(item.default for item in items[1:])


def test_tooltip_names_the_version(built) -> None:
    icon, _calls, _state = built
    assert icon.title == "Spyglass 0.41.0"


def test_menu_items_call_their_callbacks(built) -> None:
    icon, calls, _state = built
    items = list(icon.menu.items)
    items[0](icon)
    items[1](icon)
    items[3](icon)
    assert calls == ["open", "toggle", "quit"]


def test_start_with_windows_check_reads_the_entry_each_time(built) -> None:
    icon, _calls, state = built
    item = list(icon.menu.items)[1]
    assert item.checked is False
    state["autostart"] = True
    assert item.checked is True


def test_right_click_rebuilds_the_menu_before_it_opens(built) -> None:
    """The switch can change in Settings or Task Manager, so the menu is read again on open."""
    icon, _calls, _state = built
    icon._on_notify(0, WM_RBUTTONUP)
    assert icon.events == ["update_menu", f"notify:{WM_RBUTTONUP}"]
    icon.events.clear()
    icon._on_notify(0, WM_LBUTTONUP)
    assert icon.events == [f"notify:{WM_LBUTTONUP}"]


def test_placeholder_image_when_the_icon_file_is_missing(built) -> None:
    icon, _calls, _state = built
    assert isinstance(icon.icon, PIL_Image.Image)
    assert icon.icon.size == (64, 64)


def test_installer_icon_is_used_when_present(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pystray, "Icon", FakeIconBase)
    ico = tmp_path / "spyglass.ico"
    PIL_Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(ico, sizes=[(32, 32)])
    monkeypatch.setattr(tray_mod, "ICON_PATH", ico)
    icon = tray_mod.build_tray(lambda: None, lambda: None, lambda: False, lambda: None, "0.41.0")
    assert icon.icon.size == (32, 32)
    assert icon.icon.getpixel((5, 5)) == (10, 20, 30, 255)
