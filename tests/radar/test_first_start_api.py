"""The first-start routes: choose the data folder and vault, and the browser extension guide.

They run the whole app with a scratch desktop.json (SPYGLASS_DESKTOP_CONFIG), a fake platform and
a recorded restart, so no test moves real data, restarts anything or opens a browser.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.desktop.platform_base import Browser
from spyglass_service.radar.api import first_start

BASE = "/api/radar/desktop"
FOREIGN = {"Origin": "https://news.example.com", "Sec-Fetch-Site": "cross-site"}


class FakePlatform:
    def installed_browsers(self) -> list[Browser]:
        return [Browser("chrome", "Google Chrome", Path("chrome.exe"), "chrome://extensions"),
                Browser("edge", "Microsoft Edge", Path("msedge.exe"), "edge://extensions")]


class Rig:
    """An app as the desktop app builds it, with a scratch settings file beside a data folder."""

    def __init__(self, tmp_path: Path, monkeypatch, *, settings_body: dict | None,
                 started_by: str = "desktop") -> None:
        self.config = tmp_path / "config" / "desktop.json"
        self.config.parent.mkdir()
        if settings_body is not None:
            self.config.write_text(json.dumps(settings_body), encoding="utf-8")
        monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(self.config))
        monkeypatch.setattr(first_start, "install_folder", lambda: tmp_path / "Programs" / "Spyglass")
        self.data = tmp_path / "config" / "data"
        self.stops: list[str] = []
        self.restarts: list[str] = []
        settings = Settings(_env_file=None, data_dir=self.data, port=7790)
        self.app = create_app(settings, started_by=started_by, desktop_platform=FakePlatform(),
                              shutdown_handler=lambda: self.stops.append("stop"))
        self.app.state.restart_spawner = lambda: self.restarts.append("restart")
        self.client = TestClient(self.app)

    def saved(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))


@pytest.fixture()
def first(tmp_path: Path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, settings_body={"data_dir": None, "vault_path": None,
                                                    "port": 7790})
    yield rig
    rig.app.state.engine.dispose()


@pytest.fixture()
def upgraded(tmp_path: Path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, settings_body={"data_dir": str(tmp_path / "old"),
                                                    "vault_path": None, "port": 7790})
    yield rig
    rig.app.state.engine.dispose()


def test_a_first_start_is_reported_with_the_folder_in_use(first: Rig) -> None:
    body = first.client.get(f"{BASE}/first-start").json()
    assert body["needed"] is True
    assert body["data_dir"] == str(first.data)
    assert body["browsers"] == []


def test_an_upgrade_needs_no_first_start_page(upgraded: Rig) -> None:
    assert upgraded.client.get(f"{BASE}/first-start").json()["needed"] is False


def test_a_developer_run_never_shows_the_page(tmp_path: Path, monkeypatch) -> None:
    rig = Rig(tmp_path, monkeypatch, settings_body={"data_dir": None}, started_by="developer")
    try:
        assert rig.client.get(f"{BASE}/first-start").json()["needed"] is False
    finally:
        rig.app.state.engine.dispose()


def test_keeping_the_default_folder_saves_it_without_a_restart(first: Rig) -> None:
    vault = first.config.parent.parent / "vault"
    vault.mkdir()
    reply = first.client.post(f"{BASE}/first-start",
                              json={"data_dir": str(first.data), "vault_path": str(vault)})
    assert reply.status_code == 200
    assert reply.json() == {"restart": False, "data_dir": str(first.data)}
    assert first.saved() == {"data_dir": str(first.data), "vault_path": str(vault), "port": 7790}
    # The vault applies at once, as when it is saved in Settings.
    assert first.app.state.settings.vault_path == vault
    assert first.restarts == [] and first.stops == []
    assert first.client.get(f"{BASE}/first-start").json()["needed"] is False


def test_another_folder_restarts_spyglass_on_it(first: Rig, tmp_path: Path) -> None:
    chosen = tmp_path / "D drive" / "Spyglass data"
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": str(chosen),
                                                           "vault_path": None})
    assert reply.json() == {"restart": True, "data_dir": str(chosen)}
    assert first.saved()["data_dir"] == str(chosen)
    assert first.restarts == ["restart"] and first.stops == ["stop"]


def test_a_folder_with_older_data_is_refused_by_the_usual_check(first: Rig, tmp_path: Path) -> None:
    old = tmp_path / "old-data"
    old.mkdir()
    conn = sqlite3.connect(old / "spyglass.db")
    conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": str(old)})
    assert reply.status_code == 400
    assert "older Spyglass" in reply.json()["detail"]
    assert first.saved()["data_dir"] is None
    assert first.restarts == []


@pytest.mark.parametrize("folder", ["relative\\data", ""])
def test_a_folder_that_is_not_a_full_path_is_refused(first: Rig, folder: str) -> None:
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": folder})
    assert reply.status_code == 400


def test_a_folder_inside_the_program_folder_is_refused(first: Rig, tmp_path: Path) -> None:
    inside = tmp_path / "Programs" / "Spyglass" / "data"
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": str(inside)})
    assert reply.status_code == 400
    assert "program folder" in reply.json()["detail"]


def test_a_vault_that_does_not_exist_is_refused(first: Rig, tmp_path: Path) -> None:
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": str(first.data),
                                                           "vault_path": str(tmp_path / "nope")})
    assert reply.status_code == 400
    assert first.saved()["data_dir"] is None


def test_choosing_again_after_the_first_start_is_refused(upgraded: Rig) -> None:
    reply = upgraded.client.post(f"{BASE}/first-start", json={"data_dir": str(upgraded.data)})
    assert reply.status_code == 409


def test_another_site_cannot_choose_the_folder(first: Rig) -> None:
    reply = first.client.post(f"{BASE}/first-start", json={"data_dir": str(first.data)},
                              headers=FOREIGN)
    assert reply.status_code == 403
    assert first.saved()["data_dir"] is None


def test_the_guide_lists_the_browsers_setup_was_asked_for(upgraded: Rig) -> None:
    guide = upgraded.config.parent / "setup-guide.json"
    guide.write_text(json.dumps({"browsers": ["edge", "opera"]}), encoding="utf-8")
    body = upgraded.client.get(f"{BASE}/first-start").json()
    # Opera is not installed (any more), so only Edge is offered.
    assert body["browsers"] == [{"id": "edge", "name": "Microsoft Edge"}]


def test_dismissing_the_guide_removes_it(upgraded: Rig) -> None:
    guide = upgraded.config.parent / "setup-guide.json"
    guide.write_text(json.dumps({"browsers": ["edge"]}), encoding="utf-8")
    assert upgraded.client.post(f"{BASE}/setup-guide/dismiss").status_code == 204
    assert not guide.exists()
    assert upgraded.client.get(f"{BASE}/first-start").json()["browsers"] == []


def test_the_restarted_spyglass_opens_no_second_browser_tab(monkeypatch) -> None:
    """The first-start page reloads itself, so the new start runs in the background."""
    started: list[list[str]] = []

    class Recorder:
        def __init__(self, args, **_kwargs) -> None:
            started.append(list(args))

    monkeypatch.setattr(first_start.subprocess, "Popen", Recorder)
    first_start.spawn_restart()
    assert started and started[0][-2:] == ["--restart", "--background"]
