"""Regression test: when the radar owns the pipeline, /api/refresh uses the radar's collection
path (21-day age filter, switched-off feeds dropped) instead of the plain collectors."""

from fastapi.testclient import TestClient

from spyglass_service import app as app_module
from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.radar.sources import legacy


def _client(tmp_path, *, radar: bool) -> TestClient:
    """An app on a throwaway data directory, without background workers or the scheduler."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", radar_scheduler=False,
                        vault_path=None)
    return TestClient(create_app(settings, radar=radar, skip_startup_embed=True,
                                 skip_fetch_worker=True, skip_claude_worker=True))


def test_refresh_in_radar_mode_runs_the_radar_collection(tmp_path, monkeypatch) -> None:
    """A newly added feed's archive goes through the age filter, never the plain collectors."""
    calls: list[str] = []
    monkeypatch.setattr(legacy, "run_legacy_collection",
                        lambda engine, settings: calls.append("radar") or 3)
    monkeypatch.setattr(app_module, "run_refresh",
                        lambda engine, collectors: calls.append("plain") or 0)
    with _client(tmp_path, radar=True) as client:
        body = client.post("/api/refresh").json()
    assert calls == ["radar"] and body["refreshed"] is True


def test_refresh_outside_radar_mode_keeps_the_plain_collectors(tmp_path, monkeypatch) -> None:
    """The older app (tests and tools that build it without the radar) is unchanged."""
    calls: list[str] = []
    monkeypatch.setattr(legacy, "run_legacy_collection",
                        lambda engine, settings: calls.append("radar") or 0)
    monkeypatch.setattr(app_module, "run_refresh",
                        lambda engine, collectors: calls.append("plain") or 0)
    with _client(tmp_path, radar=False) as client:
        client.post("/api/refresh")
    assert calls == ["plain"]
