"""Tests for the sources endpoints, on an app that mounts only the sources router."""

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.models import Feed, RunLog
from spyglass_service.radar import capture as capture_mod
from spyglass_service.radar.api import sources as sources_api
from spyglass_service.radar.scheduler import RadarScheduler

from .test_sources_support import make_engine, make_settings


@pytest.fixture(autouse=True)
def offline_capture(monkeypatch):
    monkeypatch.setattr(capture_mod, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(capture_mod, "_default_title", lambda url: "Fetched title")


def build(tmp_path, scheduler=None):
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(sources_api.router)
    app.state.engine = engine
    app.state.settings = make_settings()
    if scheduler is not None:
        app.state.radar_scheduler = scheduler
    return engine, app


def test_capture_returns_a_radar_item_marked_from_you(tmp_path) -> None:
    engine, app = build(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post("/capture", json={"url": "https://example.com/a",
                                                     "note": "for later"})
            assert response.status_code == 200
            item = response.json()
            assert item["url"] == "https://example.com/a" and item["title"] == "Fetched title"
            assert item["source"] == "capture"
            assert item["state"]["from_user"] is True and item["state"]["captured_via"] == "manual"
            again = client.post("/capture", json={"url": "https://example.com/a#x"}).json()
            assert again["id"] == item["id"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("body", [
    {"url": "javascript:alert(1)"}, {"url": "file:///etc/passwd"},
    {"url": "http://127.0.0.1:7777/x"}, {"url": "http://192.168.0.2/"},
])
def test_capture_rejects_unsafe_links_with_400(tmp_path, body) -> None:
    engine, app = build(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post("/capture", json=body)
            assert response.status_code == 400 and response.json()["detail"]
    finally:
        engine.dispose()


def test_capture_validates_the_body(tmp_path) -> None:
    engine, app = build(tmp_path)
    try:
        with TestClient(app) as client:
            assert client.post("/capture", json={}).status_code == 422
            assert client.post("/capture", json={"url": ""}).status_code == 422
            assert client.post("/capture", json={"url": "https://e.com/", "note": "x" * 3000}
                               ).status_code == 422
    finally:
        engine.dispose()


def test_capture_kicks_assessment_when_a_scheduler_exists(tmp_path) -> None:
    kicked = []
    fake = SimpleNamespace(kick_assessment=lambda: kicked.append(1) or True)
    engine, app = build(tmp_path, fake)
    try:
        with TestClient(app) as client:
            assert client.post("/capture", json={"url": "https://example.com/k"}).status_code == 200
        assert kicked == [1]
    finally:
        engine.dispose()


def test_collect_without_a_scheduler_is_503(tmp_path) -> None:
    engine, app = build(tmp_path)
    try:
        with TestClient(app) as client:
            assert client.post("/collect").status_code == 503
    finally:
        engine.dispose()


def test_collect_starts_in_background_and_conflicts_while_running(tmp_path) -> None:
    release, started = threading.Event(), threading.Event()
    engine = make_engine(tmp_path)
    try:
        def slow():
            started.set()
            release.wait(5)

        quick = {n: (lambda: None) for n in ("radar", "raindrop", "embed", "pipeline", "compose")}
        scheduler = RadarScheduler(engine, make_settings(), lambda: None,
                                   stages={**quick, "legacy": slow})
        app = FastAPI()
        app.include_router(sources_api.router)
        app.state.engine, app.state.settings = engine, make_settings()
        app.state.radar_scheduler = scheduler
        with TestClient(app) as client:
            assert client.post("/collect").json() == {"started": True}
            assert started.wait(5)
            assert client.post("/collect").status_code == 409
            assert client.get("/status").json()["cycle_running"] is True
            release.set()
            for _ in range(100):
                if not scheduler.running:
                    break
                threading.Event().wait(0.05)
            assert client.get("/status").json()["last_cycle"]["result"] == "ok"
    finally:
        release.set()
        engine.dispose()


def test_status_without_a_scheduler_still_reports_queues(tmp_path) -> None:
    engine, app = build(tmp_path)
    try:
        with TestClient(app) as client:
            client.post("/capture", json={"url": "https://example.com/q"})
            body = client.get("/status").json()
            assert body["scheduler_running"] is False
            assert body["queues"] == {"unassessed": 1, "unembedded": 1}
            assert body["items_total"] == 1
    finally:
        engine.dispose()


def test_sources_lists_feeds_and_collectors_with_last_runs(tmp_path) -> None:
    engine, app = build(tmp_path)
    try:
        with Session(engine) as session:
            session.add(Feed(feed_url="https://f.example/feed", name="F", kind="rss",
                             added_via="seed"))
            session.add(RunLog(source="radar:news", status="ok", detail="5 new",
                               finished_at=datetime.now(UTC)))
            session.add(RunLog(source="radar:hn", status="error", detail="RuntimeError: down"))
            session.add(RunLog(source="radar:slack", status="skipped",
                               detail="not configured: no token"))
            session.commit()
        with TestClient(app) as client:
            body = client.get("/sources").json()
        assert [f["name"] for f in body["feeds"]] == ["F"] and body["feeds"][0]["item_count"] == 0
        by_key = {c["key"]: c for c in body["collectors"]}
        assert by_key["news"]["status"] == "ok" and by_key["news"]["new_items"] == 5
        assert by_key["hn"]["status"] == "error" and by_key["hn"]["new_items"] is None
        assert by_key["slack"]["status"] == "skipped"
        assert by_key["gmail"]["status"] == "never"
        assert {"rss", "raindrop"} <= set(by_key)
    finally:
        engine.dispose()
