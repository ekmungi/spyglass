"""Tests for the FastAPI application factory: health, shutdown, SPA stub, lifespan."""

from pathlib import Path

from fastapi.testclient import TestClient

from spyglass_service import __version__
from spyglass_service.app import create_app
from spyglass_service.config import Settings


def make_settings(tmp_path: Path) -> Settings:
    """Settings pointing all writable paths into the test's temp directory."""
    return Settings(_env_file=None, data_dir=tmp_path / "data")


def test_health_reports_ok_and_version(tmp_path: Path) -> None:
    """The plugin's supervision loop polls /api/health; it must report ok + version."""
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "db": "ok"}


def test_health_reports_degraded_on_corrupt_db(tmp_path: Path) -> None:
    """A malformed DB is surfaced via /api/health (still 200) rather than crash-looping."""
    settings = make_settings(tmp_path)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(b"this is not a sqlite database " * 10)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unhealthy"


def test_refresh_refused_on_corrupt_db(tmp_path: Path) -> None:
    """A degraded DB refuses /api/refresh with 409 so writes/backup never hit it."""
    settings = make_settings(tmp_path)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(b"this is not a sqlite database " * 10)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/refresh")
    assert response.status_code == 409


def test_lifespan_initializes_the_database(tmp_path: Path) -> None:
    """Starting the app creates the SQLite database inside the configured data dir."""
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        pass
    assert settings.db_path.exists()


def test_shutdown_endpoint_invokes_the_registered_handler(tmp_path: Path) -> None:
    """POST /api/shutdown asks the host process to stop (used by the Obsidian plugin)."""
    calls: list[str] = []
    app = create_app(make_settings(tmp_path), shutdown_handler=lambda: calls.append("stop"))
    with TestClient(app) as client:
        response = client.post("/api/shutdown")
    assert response.status_code == 202
    assert calls == ["stop"]


def test_root_serves_placeholder_when_no_spa_build_exists(tmp_path: Path) -> None:
    """Without a frontend build the root path still answers plainly (no white screen)."""
    app = create_app(make_settings(tmp_path), spa_dir=tmp_path / "missing-dist")
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Spyglass" in response.text


def test_root_serves_spa_index_when_build_exists(tmp_path: Path) -> None:
    """With a frontend build present, the root path serves its index.html."""
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text("<html><body>SPA build</body></html>", encoding="utf-8")
    app = create_app(make_settings(tmp_path), spa_dir=spa)
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "SPA build" in response.text


def _no_background_embed(monkeypatch) -> None:
    """Neutralize the background embed job for backup tests.

    The embed job runs in a worker thread; if its DB connection outlives
    engine.dispose() at teardown it raises a late-GC ResourceWarning that the
    suite's `filterwarnings = error` turns into a failure. Backup tests do not
    care about embeddings, so we make the job a no-op to keep them deterministic.
    """
    monkeypatch.setattr("spyglass_service.app.embed_pending_all", lambda *args, **kwargs: None)


def test_lifespan_writes_a_database_backup(tmp_path: Path, monkeypatch) -> None:
    """Startup snapshots the freshly-initialized DB so a corrupt run is recoverable."""
    from spyglass_service.backup import list_backups

    _no_background_embed(monkeypatch)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        pass
    assert len(list_backups(settings.backups_dir)) == 1


def test_refresh_writes_an_additional_backup(tmp_path: Path, monkeypatch) -> None:
    """A successful refresh takes a fresh snapshot on top of the startup backup."""
    from spyglass_service.backup import list_backups

    _no_background_embed(monkeypatch)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/refresh")
    # Startup backup plus the post-refresh backup; same-second names stay distinct.
    assert len(list_backups(settings.backups_dir)) == 2


def test_refresh_then_embeddings_exist(tmp_path: Path) -> None:
    """After a refresh, the background job embeds carded items -- no Claude session involved."""
    import time

    from sqlmodel import Session, select

    from spyglass_service.models import Card, Embedding, Item

    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        engine = app.state.engine
        # Seed an item + card so there is something to embed.
        with Session(engine) as session:
            item = Item(
                source="rss",
                external_id="e1",
                title="Alpha",
                url="https://x.test",
                summary="s",
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.add(Card(item_id=item.id, summary="s"))
            session.commit()
        client.post("/api/refresh")
        # The embed runs in a background thread; poll briefly for the row to appear.
        deadline = time.monotonic() + 5.0
        rows: list = []
        while time.monotonic() < deadline:
            with Session(engine) as session:
                rows = session.exec(select(Embedding)).all()
            if rows:
                break
            time.sleep(0.05)
    assert rows, "expected a background-embedded row after refresh"
