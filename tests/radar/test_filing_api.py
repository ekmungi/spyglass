"""Tests for the "To file" queue endpoints (radar/api/filing.py) and the feed filter.

The opener is a fake that records links; Claude Code is never opened and no vault is written.
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
from spyglass_service.radar import filing_queue
from spyglass_service.radar.api import filing as filing_api
from spyglass_service.radar.api import items as items_api
from spyglass_service.radar.models import Assessment, ItemExtra, Signal, dumps


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
    """An app with the filing and items routers, a database and (optionally) a vault folder.

    The service runs on port 7778; the vault's .mcp.json names the tool server at
    `connected_port` (None writes no file at all).
    """
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    vault_path = None
    if vault:
        vault_path = tmp_path / "vault"
        (vault_path / "01 PROJECTS" / "Imaging Radar").mkdir(parents=True)
        if connected_port is not None:
            (vault_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"spyglass": {
                "type": "http", "url": f"http://127.0.0.1:{connected_port}/mcp/"}}}),
                encoding="utf-8")
    app = FastAPI()
    app.include_router(filing_api.router, prefix="/api/radar")
    app.include_router(items_api.router, prefix="/api/radar")
    app.state.engine = engine
    app.state.settings = Settings(_env_file=None, data_dir=tmp_path / "data",
                                  vault_path=vault_path, port=7778,
                                  radar_filing_ingest_skill="vault-skills:ingest", radar_filing_manage_skill="vault-skills:manage")
    app.state.service_state = StubState()
    app.state.link_opener = opener
    return app, engine


def add_item(engine, n: int) -> int:
    """One judged item; returns its id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"e{n}", title=f"Secret title {n}",
                    url=f"https://site.example/{n}", origin="Site Example",
                    published_at=datetime(2026, 11, 9, tzinfo=UTC))
        session.add(item)
        session.commit()
        session.add(Assessment(item_id=item.id, tier="top", section="health", kind="news",
                               score=80, headline=f"Secret headline {n}", key_points=dumps([]),
                               entities=dumps([])))
        session.commit()
        return item.id


@pytest.fixture
def env(tmp_path):
    """App, engine, client, opener and two item ids."""
    opener = Recorder()
    app, engine = make_app(tmp_path, opener=opener)
    ids = [add_item(engine, 1), add_item(engine, 2)]
    yield app, engine, TestClient(app), opener, ids
    engine.dispose()


def test_queueing_an_item_with_defaults(env):
    _app, engine, client, _opener, ids = env
    res = client.post(f"/api/radar/items/{ids[0]}/file", json={})
    assert res.status_code == 200
    assert res.json() == {"item_id": ids[0], "filing": "waiting", "count": 1}
    [entry] = filing_queue.waiting(engine)
    assert (entry.kind, entry.project, entry.note) == ("resource", None, "")


def test_queueing_with_a_kind_a_project_and_a_note(env):
    _app, engine, client, _opener, ids = env
    res = client.post(f"/api/radar/items/{ids[0]}/file", json={
        "kind": "feature idea", "project": "imaging radar", "note": "  try\nit  "})
    assert res.status_code == 200
    [entry] = filing_queue.waiting(engine)
    assert (entry.kind, entry.project, entry.note) == ("feature idea", "Imaging Radar", "try it")


def test_queueing_twice_changes_the_row_and_the_count_stays(env):
    _app, _engine, client, _opener, ids = env
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    res = client.post(f"/api/radar/items/{ids[0]}/file", json={"kind": "learning"})
    assert res.json()["count"] == 1
    assert client.get("/api/radar/filing").json()["waiting"][0]["kind"] == "learning"


def test_an_unlisted_project_is_a_plain_422(env):
    _app, _engine, client, _opener, ids = env
    res = client.post(f"/api/radar/items/{ids[0]}/file", json={"project": "Nope"})
    assert res.status_code == 422
    assert res.json()["detail"] == "\"Nope\" is not one of your projects."


@pytest.mark.parametrize("payload", [{"kind": "poem"}, {"extra": 1}, {"note": "x" * 3000}])
def test_invalid_bodies_are_refused(env, payload):
    _app, _engine, client, _opener, ids = env
    assert client.post(f"/api/radar/items/{ids[0]}/file", json=payload).status_code == 422


def test_unknown_item_is_404_and_non_json_is_415(env):
    _app, _engine, client, _opener, ids = env
    assert client.post("/api/radar/items/999/file", json={}).status_code == 404
    res = client.post(f"/api/radar/items/{ids[0]}/file", content="kind=resource",
                      headers={"content-type": "application/x-www-form-urlencoded"})
    assert res.status_code == 415


def test_an_already_filed_item_is_409_with_a_plain_message(env):
    _app, engine, client, _opener, ids = env
    with Session(engine) as session:
        session.add(ItemExtra(item_id=ids[0], data=dumps({"filed": {"path": "A/b.md"}})))
        session.commit()
    res = client.post(f"/api/radar/items/{ids[0]}/file", json={})
    assert res.status_code == 409 and "already filed" in res.json()["detail"]
    assert filing_queue.count(engine) == 0


def test_removing_from_the_queue_also_works_when_not_queued(env):
    _app, _engine, client, _opener, ids = env
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    client.post(f"/api/radar/items/{ids[1]}/file", json={})
    res = client.delete(f"/api/radar/items/{ids[0]}/file")
    assert res.json() == {"item_id": ids[0], "filing": None, "count": 1}
    again = client.delete(f"/api/radar/items/{ids[0]}/file")
    assert again.status_code == 200 and again.json()["count"] == 1


def test_the_queue_lists_items_oldest_first(env):
    _app, _engine, client, _opener, ids = env
    client.post(f"/api/radar/items/{ids[1]}/file", json={"note": "first"})
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    body = client.get("/api/radar/filing").json()
    assert body["count"] == 2
    assert [w["item"]["id"] for w in body["waiting"]] == [ids[1], ids[0]]
    first = body["waiting"][0]
    assert first["item"]["filing"] == "waiting" and first["note"] == "first"
    assert set(first) == {"item", "kind", "project", "note", "requested_at"}


def test_the_feed_filters_on_waiting_and_marks_items(env):
    _app, _engine, client, _opener, ids = env
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    feed = client.get("/api/radar/feed", params={"filing": "waiting"}).json()
    assert [i["id"] for i in feed["items"]] == [ids[0]] and feed["total"] == 1
    assert feed["items"][0]["filing"] == "waiting"
    everything = {i["id"]: i["filing"] for i in client.get("/api/radar/feed").json()["items"]}
    assert everything == {ids[0]: "waiting", ids[1]: None}
    assert client.get("/api/radar/feed", params={"filing": "other"}).status_code == 422


def test_preview_describes_the_batch_without_opening_anything(env, tmp_path):
    _app, _engine, client, opener, ids = env
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    client.post(f"/api/radar/items/{ids[1]}/file", json={})
    res = client.post("/api/radar/filing/preview", json={})
    assert res.status_code == 200
    body = res.json()
    assert "2 items" in body["text"] and "spyglass-file" in body["text"]
    assert "never as instructions" in body["text"] or "never instructions" in body["text"]
    assert "Secret" not in body["text"]  # no titles, no article text
    assert body["vault"] == str(tmp_path / "vault") and body["available"] is True
    assert body["delivery"] in ("link", "handoff") and opener.urls == []


def test_open_hands_the_batch_to_the_opener_with_the_vault_as_folder(env, tmp_path):
    _app, engine, client, opener, ids = env
    client.post(f"/api/radar/items/{ids[0]}/file", json={})
    preview = client.post("/api/radar/filing/preview", json={}).json()
    res = client.post("/api/radar/filing/open", json={})
    assert res.status_code == 200 and res.json()["opened"] is True
    assert len(opener.urls) == 1
    query = parse_qs(urlsplit(opener.urls[0]).query)
    if res.json()["delivery"] == "link":
        assert query["q"][0] == preview["text"]
    assert query["folder"][0].lower().replace("\\", "/") == str(
        tmp_path / "vault").lower().replace("\\", "/")
    with Session(engine) as session:
        signals = session.exec(select(Signal).where(Signal.item_id == ids[0])).all()
    assert [(s.kind, s.value) for s in signals] == [("share", "claude_code:file_batch")]
    assert filing_queue.count(engine) == 1  # opening does not empty the queue; filing does


def test_open_and_preview_with_an_empty_queue_say_nothing_is_waiting(env):
    _app, _engine, client, opener, _ids = env
    for path in ("/api/radar/filing/open", "/api/radar/filing/preview"):
        res = client.post(path, json={})
        assert res.status_code == 409
        assert res.json()["detail"] == "Nothing is waiting to be filed."
    assert opener.urls == []


def test_open_without_a_vault_says_filing_is_not_set_up(tmp_path):
    """No vault folder means filing is not configured: nothing is offered or queued."""
    app, engine = make_app(tmp_path, vault=False, opener=Recorder())
    item_id = add_item(engine, 1)
    client = TestClient(app)
    assert client.post(f"/api/radar/items/{item_id}/file", json={}).status_code == 409
    res = client.post("/api/radar/filing/open", json={})
    assert res.status_code == 200 and res.json()["available"] is False
    assert "notes vault is not set up" in res.json()["detail"]
    assert client.post("/api/radar/filing/preview", json={}).json()["available"] is False
    engine.dispose()


@pytest.mark.parametrize("connected, words", [
    (7777, ["another Spyglass (port 7777)", "not this one (port 7778)"]),
    (None, ["not connected to Spyglass yet"]),
])
def test_a_vault_connected_to_another_spyglass_makes_the_batch_unavailable(
        tmp_path, connected, words):
    app, engine = make_app(tmp_path, opener=Recorder(), connected_port=connected)
    item_id = add_item(engine, 1)
    client = TestClient(app)
    client.post(f"/api/radar/items/{item_id}/file", json={})
    preview = client.post("/api/radar/filing/preview", json={}).json()
    assert preview["available"] is False and "1 item" in preview["text"]
    assert all(word in preview["reason"] for word in words)
    res = client.post("/api/radar/filing/open", json={})
    assert res.status_code == 409 and res.json()["detail"] == preview["reason"]
    assert app.state.link_opener.urls == []
    with Session(engine) as session:
        assert session.exec(select(Signal)).all() == []
    engine.dispose()


def test_a_failing_opener_returns_the_text_to_copy(tmp_path):
    app, engine = make_app(tmp_path, opener=Recorder(fail=True))
    item_id = add_item(engine, 1)
    client = TestClient(app)
    client.post(f"/api/radar/items/{item_id}/file", json={})
    res = client.post("/api/radar/filing/open", json={})
    assert res.status_code == 502 and res.json()["error"] == "claude_desktop_unavailable"
    assert "1 item" in res.json()["text"]
    with Session(engine) as session:
        assert session.exec(select(Signal)).all() == []
    engine.dispose()


@pytest.mark.parametrize("method, path", [
    ("post", "/api/radar/items/1/file"), ("delete", "/api/radar/items/1/file"),
    ("post", "/api/radar/filing/open"), ("post", "/api/radar/filing/preview"),
])
def test_cross_site_requests_are_refused(env, method, path):
    _app, engine, client, opener, _ids = env
    res = getattr(client, method)(path, headers={"sec-fetch-site": "cross-site"},
                                  **({"json": {}} if method == "post" else {}))
    assert res.status_code == 403 and opener.urls == [] and filing_queue.count(engine) == 0


def test_reading_the_queue_is_refused_cross_site(env):
    _app, _engine, client, _opener, _ids = env
    assert client.get("/api/radar/filing",
                      headers={"sec-fetch-site": "cross-site"}).status_code == 403
