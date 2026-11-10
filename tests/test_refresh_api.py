"""Tests for the refresh and activity endpoints."""

import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import RunLog


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings))


def test_refresh_runs_and_reports_runs_in_activity(tmp_path: Path) -> None:
    """POST /api/refresh executes collectors and the run shows in /api/runs."""
    with make_client(tmp_path) as client:
        response = client.post("/api/refresh")
        assert response.status_code == 200
        runs = client.get("/api/runs").json()
    # No sources are configured in this test, so the refresh logs a single
    # zero-source run marker rather than failing.
    assert response.json()["sources"] == 0
    assert isinstance(runs, list)


def test_refresh_if_stale_skips_when_fresh(tmp_path: Path) -> None:
    """if_stale=true right after a successful refresh does not run again."""
    with make_client(tmp_path) as client:
        first = client.post("/api/refresh").json()
        second = client.post("/api/refresh", params={"if_stale": "true"}).json()
    assert first["refreshed"] is True
    assert second["refreshed"] is False


def test_not_stale_refresh_still_triggers_compose(tmp_path: Path, monkeypatch) -> None:
    """Opening the app fires an if_stale refresh; when data is still fresh
    the collection is skipped, but a local publish-day may have closed since the last
    pass -- so compose must still run (idempotently) rather than waiting for a restart."""
    import spyglass_service.app as app_module

    fired = threading.Event()

    def spy(engine, index, settings, **kwargs):
        fired.set()
        return []

    # Redirect the app's compose call (resolved from the module namespace at call time).
    monkeypatch.setattr(app_module, "compose_due_briefs", spy)

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    # skip_startup_embed so the ONLY compose trigger under test is the not-stale refresh.
    with TestClient(create_app(settings, skip_startup_embed=True)) as client:
        engine = client.app.state.engine
        # Seed a fresh successful run so is_stale() is False -> the if_stale path takes the
        # "data still fresh, skip collection" early return.
        with Session(engine) as s:
            s.add(RunLog(source="refresh", status="ok",
                         started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
            s.commit()
        resp = client.post("/api/refresh", params={"if_stale": "true"})
        assert resp.status_code == 200
        assert resp.json()["refreshed"] is False  # collection skipped (data fresh)...
        assert fired.wait(timeout=5)  # ...but compose still fired on the refresh cadence


def test_runs_endpoint_returns_latest_first(tmp_path: Path) -> None:
    """Activity rows come newest-first for the dashboard's Activity tab."""
    with make_client(tmp_path) as client:
        client.post("/api/refresh")
        client.post("/api/refresh")
        runs = client.get("/api/runs").json()
    assert len(runs) >= 2
    assert runs[0]["started_at"] >= runs[-1]["started_at"]
