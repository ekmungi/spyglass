"""Tests for the watch endpoints, on an app that mounts only the watch router."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spyglass_service.radar.api import watch as watch_api
from spyglass_service.radar.watch.discover import DiscoverResult

from .test_brief_seed import make_engine


@pytest.fixture
def client(tmp_path):
    """A TestClient for an app with only the watch router."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(watch_api.router)
    app.state.engine = engine
    app.state.settings = SimpleNamespace(openrouter_api_key=None)
    with TestClient(app) as c:
        yield c
    engine.dispose()


def test_empty_register(client) -> None:
    assert client.get("/watch").json() == {"categories": [], "suggested": []}


def test_add_patch_delete_flow(client) -> None:
    created = client.post("/watch", json={"name": "Acme", "kind": "lab", "category": "AI labs"})
    assert created.status_code == 201 and created.json()["status"] == "active"
    eid = created.json()["id"]
    body = client.get("/watch").json()
    assert body["categories"][0]["name"] == "AI labs"
    assert body["categories"][0]["entities"][0]["recent"] == []
    patched = client.patch(f"/watch/{eid}", json={"status": "muted", "category": "Other labs"})
    assert patched.json()["status"] == "muted" and patched.json()["category"] == "Other labs"
    assert client.delete(f"/watch/{eid}").json() == {"deleted": eid}
    assert client.get("/watch").json()["categories"] == []


def test_validation_and_error_statuses(client) -> None:
    client.post("/watch", json={"name": "Acme"})
    assert client.post("/watch", json={"name": "acme"}).status_code == 409
    assert client.post("/watch", json={"name": ""}).status_code == 422
    assert client.post("/watch", json={"name": "X", "kind": "spaceship"}).status_code == 422
    assert client.patch("/watch/999", json={"status": "active"}).status_code == 404
    assert client.patch("/watch/1", json={"status": "bogus"}).status_code == 422
    assert client.delete("/watch/999").status_code == 404


def test_discover_returns_suggestions(client, monkeypatch) -> None:
    def fake(engine, settings, topic):
        return DiscoverResult(accepted=[{"name": "Newco", "status": "suggested"}], rejected=["Ghost"], existing=[])

    monkeypatch.setattr(watch_api, "discover_detailed", fake)
    body = client.post("/watch/discover", json={"topic": "surgical robotics"}).json()
    assert body == {"suggested": [{"name": "Newco", "status": "suggested"}], "rejected": 1, "already_known": 0}


def test_discover_without_a_model_is_503_and_empty_topic_is_422(client) -> None:
    assert client.post("/watch/discover", json={"topic": "surgical robotics"}).status_code == 503
    assert client.post("/watch/discover", json={"topic": ""}).status_code == 422
