"""Tests for the "Open in Claude Code" and project-directory endpoints (radar/api/bridge.py).

The opener is a fake that records links; the real Claude Code application is never opened.
"""

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.claude_link import HandoffStore
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.api import bridge as bridge_api
from spyglass_service.radar.models import Assessment, ItemState, Signal, dumps

JSON = {"content-type": "application/json"}


class StubState:
    """Stands in for the service state: only the hand-off store is used."""

    def __init__(self) -> None:
        self.handoffs = HandoffStore()


class Recorder:
    """A fake opener that records each link, or fails when told to."""

    def __init__(self, fail: bool = False) -> None:
        self.urls: list[str] = []
        self.fail = fail

    def __call__(self, url: str) -> None:
        if self.fail:
            raise OSError("no handler")
        self.urls.append(url)


def make_app(tmp_path, *, vault: bool = True, opener=None, connected_port: int | None = 7778):
    """An app with only the bridge router, a database and (optionally) a vault folder.

    The service runs on port 7778; the vault's .mcp.json names the tool server at
    `connected_port` (None writes no file at all).
    """
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    vault_path = None
    if vault:
        vault_path = tmp_path / "vault"
        (vault_path / "01 PROJECTS" / "Imaging Radar").mkdir(parents=True)
        (vault_path / "01 PROJECTS" / "Career").mkdir(parents=True)
        if connected_port is not None:
            (vault_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"spyglass": {
                "type": "http", "url": f"http://127.0.0.1:{connected_port}/mcp/"}}}),
                encoding="utf-8")
    app = FastAPI()
    app.include_router(bridge_api.router, prefix="/api/radar")
    app.state.engine = engine
    app.state.settings = Settings(_env_file=None, data_dir=tmp_path / "data",
                                  vault_path=vault_path, port=7778)
    app.state.service_state = StubState()
    app.state.link_opener = opener
    return app, engine


@pytest.fixture
def env(tmp_path):
    """App, engine, client and opener, with one item whose note names a project."""
    opener = Recorder()
    app, engine = make_app(tmp_path, opener=opener)
    with Session(engine) as session:
        item = Item(source="capture", external_id="e1", title="A paper on scan triage",
                    url="https://papers.example/1", origin="Papers Example",
                    published_at=datetime(2026, 11, 9, tzinfo=UTC))
        session.add(item)
        session.commit()
        session.add(Assessment(item_id=item.id, tier="notable", section="health", score=70,
                               headline="Scan triage paper", key_points=dumps(["One point."]),
                               entities=dumps([])))
        session.add(ItemState(item_id=item.id, from_user=True,
                              user_note="for imaging radar, later"))
        session.commit()
        item_id = item.id
    yield app, engine, TestClient(app), opener, item_id
    engine.dispose()


def test_preview_shows_the_exact_text_the_vault_and_a_project_hint(env, tmp_path):
    _app, _engine, client, opener, item_id = env
    res = client.post(f"/api/radar/items/{item_id}/claude/preview", json={"intent": "file"})
    assert res.status_code == 200
    body = res.json()
    assert body["text"].startswith(f'Spyglass item {item_id}: "Scan triage paper"')
    assert body["vault"] == str(tmp_path / "vault")
    assert body["available"] is True and body["reason"] is None
    assert body["delivery"] in ("link", "handoff")
    assert body["project_hint"] == {"name": "Imaging Radar", "source": "note"}
    assert opener.urls == []  # a preview never opens anything


def test_open_hands_the_same_text_to_the_opener_and_records_a_share(env, tmp_path):
    _app, engine, client, opener, item_id = env
    payload = {"intent": "file", "project": "Imaging Radar", "as_kind": "resource"}
    preview = client.post(f"/api/radar/items/{item_id}/claude/preview", json=payload).json()
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json=payload)
    assert res.status_code == 200 and res.json()["opened"] is True
    assert len(opener.urls) == 1
    url = opener.urls[0]
    assert url.startswith("claude://code/new?")
    query = parse_qs(urlsplit(url).query)
    if res.json()["delivery"] == "link":
        assert query["q"][0] == preview["text"]
    assert query["folder"][0].lower().replace("\\", "/") == str(
        tmp_path / "vault").lower().replace("\\", "/")
    with Session(engine) as session:
        signals = session.exec(select(Signal).where(Signal.item_id == item_id)).all()
    assert [(s.kind, s.value) for s in signals] == [("share", "claude_code:file")]


def test_open_refuses_without_a_vault_folder(tmp_path):
    app, engine = make_app(tmp_path, vault=False, opener=Recorder())
    with Session(engine) as session:
        item = Item(source="rss", external_id="e", title="T", url="https://x.example/")
        session.add(item)
        session.commit()
        item_id = item.id
    client = TestClient(app)
    preview = client.post(f"/api/radar/items/{item_id}/claude/preview",
                          json={"intent": "discuss"}).json()
    assert preview["available"] is False and "vault" in preview["reason"]
    assert preview["vault"] is None and preview["delivery"] is None
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json={"intent": "discuss"})
    assert res.status_code == 409 and "vault" in res.json()["detail"]
    assert app.state.link_opener.urls == []
    engine.dispose()


def add_plain_item(engine) -> int:
    """One bare item; returns its id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id="e", title="T", url="https://x.example/")
        session.add(item)
        session.commit()
        return item.id


@pytest.mark.parametrize("connected, words", [
    (7777, ["another Spyglass (port 7777)", "not this one (port 7778)"]),
    (None, ["not connected to Spyglass yet"]),
])
def test_a_vault_connected_to_another_spyglass_makes_the_hand_off_unavailable(
        tmp_path, connected, words):
    app, engine = make_app(tmp_path, opener=Recorder(), connected_port=connected)
    item_id = add_plain_item(engine)
    client = TestClient(app)
    preview = client.post(f"/api/radar/items/{item_id}/claude/preview",
                          json={"intent": "file"}).json()
    assert preview["available"] is False
    assert all(word in preview["reason"] for word in words)
    assert preview["text"].startswith(f"Spyglass item {item_id}")  # the text is still shown
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json={"intent": "file"})
    assert res.status_code == 409 and res.json()["detail"] == preview["reason"]
    assert app.state.link_opener.urls == []
    with Session(engine) as session:
        assert session.exec(select(Signal).where(Signal.item_id == item_id)).all() == []
    engine.dispose()


def test_open_refuses_without_an_opener(tmp_path):
    app, engine = make_app(tmp_path, opener=None)
    with Session(engine) as session:
        item = Item(source="rss", external_id="e", title="T", url="https://x.example/")
        session.add(item)
        session.commit()
        item_id = item.id
    client = TestClient(app)
    preview = client.post(f"/api/radar/items/{item_id}/claude/preview",
                          json={"intent": "discuss"}).json()
    assert preview["available"] is False and "cannot open" in preview["reason"]
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json={"intent": "discuss"})
    assert res.status_code == 409
    engine.dispose()


def test_a_failing_opener_returns_the_text_to_copy(tmp_path):
    app, engine = make_app(tmp_path, opener=Recorder(fail=True))
    with Session(engine) as session:
        item = Item(source="rss", external_id="e", title="T", url="https://x.example/")
        session.add(item)
        session.commit()
        item_id = item.id
    res = TestClient(app).post(f"/api/radar/items/{item_id}/claude/open",
                               json={"intent": "discuss"})
    assert res.status_code == 502
    assert res.json()["error"] == "claude_desktop_unavailable"
    assert res.json()["text"].startswith(f"Spyglass item {item_id}")
    with Session(engine) as session:
        assert session.exec(select(Signal)).all() == []
    engine.dispose()


@pytest.mark.parametrize("payload, status", [
    ({"intent": "nonsense"}, 422),
    ({"intent": "custom"}, 422),
    ({"intent": "file", "as_kind": "everything"}, 422),
    ({"intent": "file", "extra": 1}, 422),
    ({}, 422),
])
def test_invalid_bodies_are_refused(env, payload, status):
    _app, _engine, client, opener, item_id = env
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json=payload)
    assert res.status_code == status and opener.urls == []


def test_unknown_item_and_non_json_body(env):
    _app, _engine, client, _opener, _item_id = env
    assert client.post("/api/radar/items/999/claude/preview",
                       json={"intent": "file"}).status_code == 404
    res = client.post("/api/radar/items/999/claude/open", content="intent=file",
                      headers={"content-type": "application/x-www-form-urlencoded"})
    assert res.status_code == 415


def test_cross_site_requests_are_refused(env):
    _app, _engine, client, opener, item_id = env
    res = client.post(f"/api/radar/items/{item_id}/claude/open", json={"intent": "file"},
                      headers={"sec-fetch-site": "cross-site"})
    assert res.status_code == 403 and opener.urls == []


def test_projects_directory_get_and_put(env):
    _app, _engine, client, _opener, _item_id = env
    res = client.get("/api/radar/projects")
    assert res.status_code == 200
    assert res.json() == {"projects": [
        {"name": "Career", "description": "", "in_vault": True},
        {"name": "Imaging Radar", "description": "", "in_vault": True},
    ]}
    put = client.put("/api/radar/projects", json={"projects": [
        {"name": "Imaging Radar", "description": "Radiology AI research"},
        {"name": "Side idea", "description": "Not a folder yet"},
    ]})
    assert put.status_code == 200
    assert put.json()["projects"] == [
        {"name": "Career", "description": "", "in_vault": True},
        {"name": "Imaging Radar", "description": "Radiology AI research", "in_vault": True},
        {"name": "Side idea", "description": "Not a folder yet", "in_vault": False},
    ]
    assert client.get("/api/radar/projects").json() == put.json()


def test_projects_put_validation(env):
    _app, _engine, client, _opener, _item_id = env
    too_long = client.put("/api/radar/projects",
                          json={"projects": [{"name": "x", "description": "d" * 201}]})
    assert too_long.status_code == 422
    repeated = client.put("/api/radar/projects", json={"projects": [
        {"name": "A", "description": "a"}, {"name": "a", "description": "b"}]})
    assert repeated.status_code == 422
    assert client.put("/api/radar/projects", json={"wrong": []}).status_code == 422


def test_projects_without_a_vault_is_the_stored_list_only(tmp_path):
    app, engine = make_app(tmp_path, vault=False)
    client = TestClient(app)
    assert client.get("/api/radar/projects").json() == {"projects": []}
    engine.dispose()
