"""The background filing settings in the settings API: served, validated, saved."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spyglass_service import api_settings
from spyglass_service.config import Settings, apply_overlay


def make_client(tmp_path: Path) -> tuple[TestClient, Settings]:
    """A small app holding only the settings router."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(api_settings.router)
    app.state.settings = settings
    return TestClient(app), settings


def test_the_filing_settings_are_served_with_their_defaults(tmp_path: Path) -> None:
    client, _settings = make_client(tmp_path)
    body = client.get("/api/settings").json()
    assert (body["radar_filing_mode"], body["radar_filing_quiet_minutes"],
            body["radar_filing_daily_time"], body["radar_filing_model"]) == ("off", 10, "21:00",
                                                                             "sonnet")


def test_the_filing_settings_are_saved_and_survive_a_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")
    client, settings = make_client(tmp_path)
    body = client.patch("/api/settings", json={
        "radar_filing_mode": "plan_first", "radar_filing_quiet_minutes": 15,
        "radar_filing_daily_time": "20:30", "radar_filing_model": "haiku"}).json()
    assert body["radar_filing_mode"] == "plan_first" and settings.radar_filing_mode == "plan_first"
    reloaded = apply_overlay(Settings(_env_file=None, data_dir=tmp_path / "data"))
    assert (reloaded.radar_filing_mode, reloaded.radar_filing_quiet_minutes,
            reloaded.radar_filing_daily_time, reloaded.radar_filing_model) == (
        "plan_first", 15, "20:30", "haiku")


def test_bad_filing_settings_are_refused(tmp_path: Path) -> None:
    client, settings = make_client(tmp_path)
    for body in ({"radar_filing_mode": "always"}, {"radar_filing_quiet_minutes": 1},
                 {"radar_filing_daily_time": "25:00"}, {"radar_filing_model": "a b; rm"}):
        assert client.patch("/api/settings", json=body).status_code == 422
    assert settings.radar_filing_mode == "off"


def test_a_background_mode_is_refused_while_background_filing_is_locked(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", raising=False)
    client, settings = make_client(tmp_path)
    for mode in ("auto", "plan_first"):
        reply = client.patch("/api/settings", json={"radar_filing_mode": mode})
        assert reply.status_code == 422
        assert "Background filing is not available in this version." in reply.text
    assert settings.radar_filing_mode == "off"
    assert client.patch("/api/settings", json={"radar_filing_mode": "off"}).status_code == 200
    assert client.patch("/api/settings", json={"radar_filing_quiet_minutes": 20}).status_code == 200


def test_a_stored_background_mode_is_served_as_off_while_locked(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", raising=False)
    client, settings = make_client(tmp_path)
    settings.radar_filing_mode = "auto"  # left over from an earlier version
    assert client.get("/api/settings").json()["radar_filing_mode"] == "off"
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")
    assert client.get("/api/settings").json()["radar_filing_mode"] == "auto"
