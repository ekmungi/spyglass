"""Tests for the paper search endpoint, on an app that mounts only the papers router."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spyglass_service.radar.api import papers as papers_api

from .test_brief_seed import make_engine


@pytest.fixture
def client(tmp_path):
    """A TestClient for an app with only the papers router."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(papers_api.router)
    app.state.engine = engine
    app.state.settings = SimpleNamespace(openrouter_api_key=None)
    app.state.service_state = SimpleNamespace(ensure_index=lambda: None)
    with TestClient(app) as c:
        yield c
    engine.dispose()


def test_search_passes_topic_and_limit_and_returns_status_and_notice(client, monkeypatch) -> None:
    got = {}

    def fake(engine, settings, index, topic, limit):
        got.update(topic=topic, limit=limit, index=index)
        return {"papers": [{"title": "P"}], "status": "degraded", "notice": "Ranking was unavailable."}

    monkeypatch.setattr(papers_api, "find_papers", fake)
    resp = client.post("/papers/search", json={"topic": "  polyp detection ", "limit": 3})
    assert resp.json() == {"papers": [{"title": "P"}], "status": "degraded", "notice": "Ranking was unavailable."}
    assert got == {"topic": "polyp detection", "limit": 3, "index": None}


def test_search_validation(client) -> None:
    assert client.post("/papers/search", json={"topic": ""}).status_code == 422
    assert client.post("/papers/search", json={"topic": "ok topic", "limit": 0}).status_code == 422
    assert client.post("/papers/search", json={"topic": "ok topic", "limit": 99}).status_code == 422


def test_search_failure_is_a_502(client, monkeypatch) -> None:
    def boom(*args):
        raise RuntimeError("x")

    monkeypatch.setattr(papers_api, "find_papers", boom)
    assert client.post("/papers/search", json={"topic": "ok topic"}).status_code == 502
