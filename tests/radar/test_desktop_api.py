"""The Settings routes for the desktop app: start with Windows and the browser extensions page.

They run the whole app with a fake platform, so no test touches the registry or opens a browser.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.desktop.platform_base import Browser

BASE = "/api/radar/desktop"
FOREIGN = {"Origin": "https://news.example.com", "Sec-Fetch-Site": "cross-site"}


class FakePlatform:
    """An in-memory DesktopPlatform that records what the routes ask of it."""

    def __init__(self, *, locked: bool = False) -> None:
        # locked: reading or writing the start-up entry raises PermissionError, as a
        # policy-locked Run key does.
        self.locked = locked
        self.autostart = False
        self.opened: list[str] = []
        self.browsers = [
            Browser("chrome", "Google Chrome", Path("chrome.exe"), "chrome://extensions"),
            Browser("edge", "Microsoft Edge", Path("msedge.exe"), "edge://extensions"),
        ]

    def autostart_enabled(self) -> bool:
        if self.locked:
            raise PermissionError("Run key is locked")
        return self.autostart

    def set_autostart(self, enabled: bool) -> None:
        if self.locked:
            raise PermissionError("Run key is locked")
        self.autostart = enabled

    def installed_browsers(self) -> list[Browser]:
        return list(self.browsers)

    def open_extensions_page(self, browser_id: str) -> None:
        if browser_id not in {b.id for b in self.browsers}:
            raise KeyError(browser_id)
        self.opened.append(browser_id)

    def show_message(self, title: str, text: str) -> None:
        raise AssertionError("the routes never show a message box")


def make_client(tmp_path: Path, *, started_by: str, platform: FakePlatform | None):
    """A test client on an app built with the given entry and platform; the caller disposes it."""
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    app = create_app(settings, started_by=started_by, desktop_platform=platform)
    return TestClient(app), app


@pytest.fixture()
def desktop(tmp_path: Path):
    platform = FakePlatform()
    client, app = make_client(tmp_path, started_by="desktop", platform=platform)
    yield client, platform
    app.state.engine.dispose()


def test_autostart_is_unavailable_for_the_developer_entry(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, started_by="developer", platform=FakePlatform())
    try:
        assert client.get(f"{BASE}/autostart").json() == {"available": False, "enabled": False}
        refused = client.put(f"{BASE}/autostart", json={"enabled": True})
        assert refused.status_code == 409
    finally:
        app.state.engine.dispose()


def test_autostart_is_unavailable_without_a_platform(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, started_by="desktop", platform=None)
    try:
        assert client.get(f"{BASE}/autostart").json() == {"available": False, "enabled": False}
        assert client.put(f"{BASE}/autostart", json={"enabled": True}).status_code == 409
        assert client.get(f"{BASE}/browsers").json() == []
    finally:
        app.state.engine.dispose()


def test_autostart_toggle_writes_through_the_platform(desktop) -> None:
    client, platform = desktop
    assert client.get(f"{BASE}/autostart").json() == {"available": True, "enabled": False}

    on = client.put(f"{BASE}/autostart", json={"enabled": True})
    assert on.status_code == 200
    assert on.json() == {"available": True, "enabled": True}
    assert platform.autostart is True
    assert client.get(f"{BASE}/autostart").json() == {"available": True, "enabled": True}

    off = client.put(f"{BASE}/autostart", json={"enabled": False})
    assert off.json() == {"available": True, "enabled": False}
    assert platform.autostart is False


def test_autostart_read_refused_by_windows_reports_unavailable(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, started_by="desktop", platform=FakePlatform(locked=True))
    try:
        reply = client.get(f"{BASE}/autostart")
        assert reply.status_code == 200
        assert reply.json() == {"available": False, "enabled": False}
    finally:
        app.state.engine.dispose()


def test_autostart_write_refused_by_windows_answers_503(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, started_by="desktop", platform=FakePlatform(locked=True))
    try:
        reply = client.put(f"{BASE}/autostart", json={"enabled": True})
        assert reply.status_code == 503
        assert reply.json()["detail"] == "Windows refused access to the start-up setting."
    finally:
        app.state.engine.dispose()


def test_autostart_rejects_a_body_without_a_boolean(desktop) -> None:
    client, platform = desktop
    assert client.put(f"{BASE}/autostart", json={}).status_code == 422
    assert platform.autostart is False


def test_browsers_and_open_extensions_page(desktop) -> None:
    client, platform = desktop
    assert client.get(f"{BASE}/browsers").json() == [
        {"id": "chrome", "name": "Google Chrome"},
        {"id": "edge", "name": "Microsoft Edge"},
    ]

    opened = client.post(f"{BASE}/open-extensions", json={"browser": "edge"})
    assert opened.status_code == 204
    assert platform.opened == ["edge"]

    unknown = client.post(f"{BASE}/open-extensions", json={"browser": "netscape"})
    assert unknown.status_code == 404
    assert platform.opened == ["edge"]


def test_desktop_routes_refuse_cross_site_requests(desktop) -> None:
    client, platform = desktop
    assert client.get(f"{BASE}/autostart", headers=FOREIGN).status_code == 403
    assert client.get(f"{BASE}/browsers", headers=FOREIGN).status_code == 403
    assert client.put(f"{BASE}/autostart", json={"enabled": True},
                      headers=FOREIGN).status_code == 403
    assert client.post(f"{BASE}/open-extensions", json={"browser": "chrome"},
                       headers=FOREIGN).status_code == 403
    assert platform.autostart is False
    assert platform.opened == []


def test_extension_folder_route_returns_the_copy(desktop) -> None:
    client, _ = desktop
    data = Path(client.app.state.settings.data_dir)
    response = client.get(f"{BASE}/extension")
    assert response.status_code == 200
    assert Path(response.json()["folder"]) == data / "browser-extension"


def test_extension_folder_route_refuses_cross_site_requests(desktop) -> None:
    client, _ = desktop
    assert client.get(f"{BASE}/extension", headers=FOREIGN).status_code == 403
