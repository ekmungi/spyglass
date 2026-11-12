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


def test_startup_backup_skipped_on_a_full_disk_is_logged_as_skipped(tmp_path: Path, monkeypatch) -> None:
    """A refused snapshot (too little free space) is a skipped run-log row, and startup goes on."""
    from sqlmodel import Session, select

    from spyglass_service import backup as backup_mod
    from spyglass_service.models import RunLog

    _no_background_embed(monkeypatch)
    settings = make_settings(tmp_path)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    (settings.backups_dir / "spyglass-20260101-030000.db").write_bytes(b"x" * 100)
    monkeypatch.setattr(backup_mod, "_free_bytes", lambda _folder: 1)
    app = create_app(settings)
    with TestClient(app):
        pass
    with Session(app.state.engine) as session:
        rows = session.exec(select(RunLog).where(RunLog.source == "backup")).all()
    assert [r.status for r in rows] == ["skipped"]
    assert "disk" in (rows[0].detail or "").lower()


def test_startup_moves_files_you_sent_in_out_of_the_caches(tmp_path: Path, monkeypatch) -> None:
    """A picture sent in that is still in the image cache is safe in its own store after start-up."""
    from sqlmodel import Session

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.models import Item
    from spyglass_service.radar import from_you_store, media_proxy
    from spyglass_service.radar.import_image import image_fields
    from spyglass_service.radar.models import ItemState, ReaderDoc

    _no_background_embed(monkeypatch)
    settings = make_settings(tmp_path)
    url = "https://team.slack.com/files/U1/F200/chart.png"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    seed = create_db_engine(settings.db_path)
    init_db(seed)
    with Session(seed) as session:
        item = Item(source="capture", external_id=url, title="chart", url=url)
        session.add(item)
        session.commit()
        session.add(ReaderDoc(item_id=item.id, html=image_fields(url, "chart", None)["html"],
                              lead_image=url, source_url=url))
        session.add(ItemState(item_id=item.id, from_user=True, captured_via="slack"))
        session.commit()
        item_id = item.id
    seed.dispose()
    media_proxy.cache_put(settings.data_dir / "img_cache", url, png, "image/png")

    with TestClient(create_app(settings)):
        pass

    assert from_you_store.find(settings.data_dir, item_id)[0].read_bytes() == png
