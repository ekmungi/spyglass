"""Tests for the group and review endpoints, on an app that mounts only the watch router."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.radar.api import watch as watch_api
from spyglass_service.radar.api import watch_manage
from spyglass_service.models import Item
from spyglass_service.radar.models import ItemEntity, utcnow
from spyglass_service.radar.watch import registry

from .test_brief_seed import add_item, make_engine


@pytest.fixture
def client(tmp_path):
    """A TestClient (and the engine) for an app with only the watch router and no model."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(watch_api.router)
    app.state.engine = engine
    app.state.settings = SimpleNamespace(openrouter_api_key=None)
    with TestClient(app) as c:
        c.engine = engine
        yield c
    engine.dispose()


def add(client, name: str, category: str = "Endoscopy AI", **extra) -> dict:
    """Follow a name through the API."""
    response = client.post("/watch", json={"name": name, "category": category, **extra})
    assert response.status_code == 201
    return response.json()


def link_fresh_item(client, entity_id: int, title: str) -> None:
    """Store an item fetched just now (the API counts a real 7-day window) and link it."""
    item_id = add_item(client.engine, title)
    with Session(client.engine) as s:
        s.get(Item, item_id).fetched_at = utcnow().replace(tzinfo=None)
        s.add(ItemEntity(item_id=item_id, entity_id=entity_id))
        s.commit()


def group(register: dict, name: str) -> dict:
    """The category called `name` in a register payload."""
    return next(c for c in register["categories"] if c["name"] == name)


def test_get_watch_carries_week_counts_and_the_paused_flag(client) -> None:
    entity = add(client, "Alpha Scopes")
    link_fresh_item(client, entity["id"], "story")
    body = client.get("/watch").json()
    endo = group(body, "Endoscopy AI")
    assert endo["week_count"] == 1 and endo["paused"] is False
    assert endo["entities"][0]["week_count"] == 1


def test_pause_resume_rename_and_move_answer_the_fresh_register(client) -> None:
    add(client, "Alpha Scopes")
    add(client, "Beta Vision")
    paused = client.patch("/watch/groups", json={"category": "Endoscopy AI", "action": "pause"})
    assert paused.status_code == 200 and group(paused.json(), "Endoscopy AI")["paused"] is True
    assert paused.json()["removed"] == []
    resumed = client.patch("/watch/groups", json={"category": "Endoscopy AI", "action": "resume"}).json()
    assert group(resumed, "Endoscopy AI")["paused"] is False
    renamed = client.patch("/watch/groups", json={"category": "Endoscopy AI", "action": "rename", "to": "Scopes"}).json()
    assert [c["name"] for c in renamed["categories"]] == ["Scopes"]
    moved = client.patch("/watch/groups", json={"category": "Scopes", "action": "move", "to": "Devices"}).json()
    assert [c["name"] for c in moved["categories"]] == ["Devices"]


def test_remove_returns_the_entries_and_restore_brings_them_back(client) -> None:
    entity = add(client, "Alpha Scopes")
    add(client, "Beta Vision")
    link_fresh_item(client, entity["id"], "story")
    removed = client.patch("/watch/groups", json={"category": "Endoscopy AI", "action": "remove"}).json()
    assert removed["categories"] == [] and len(removed["removed"]) == 2
    back = client.post("/watch/groups/restore", json={"entries": removed["removed"]}).json()
    assert back["restored"] == 2
    entities = group(back, "Endoscopy AI")["entities"]
    assert {e["name"] for e in entities} == {"Alpha Scopes", "Beta Vision"}
    assert next(e for e in entities if e["name"] == "Alpha Scopes")["week_count"] == 1


def test_group_errors_are_readable_statuses(client) -> None:
    add(client, "Alpha Scopes")
    patch = client.patch
    assert patch("/watch/groups", json={"category": "Nowhere", "action": "pause"}).status_code == 404
    assert patch("/watch/groups", json={"category": "Endoscopy AI", "action": "explode"}).status_code == 422
    assert patch("/watch/groups", json={"category": "Endoscopy AI", "action": "rename"}).status_code == 422
    long = patch("/watch/groups", json={"category": "Endoscopy AI", "action": "rename", "to": "x" * 61})
    assert long.status_code == 422 and "60" in long.json()["detail"]
    lines = patch("/watch/groups", json={"category": "Endoscopy AI", "action": "rename", "to": "a\nb"})
    assert lines.status_code == 422
    assert patch("/watch/groups", json={"category": "", "action": "pause"}).status_code == 422
    assert client.post("/watch/groups/restore", json={"entries": [{"name": "", "kind": "company"}]}).status_code == 422
    assert group(client.get("/watch").json(), "Endoscopy AI")["entities"][0]["name"] == "Alpha Scopes"


def test_the_group_route_is_not_taken_for_an_entity_id(client) -> None:
    assert client.patch("/watch/groups", json={"category": "X", "action": "pause"}).status_code == 404
    assert client.patch("/watch/7", json={"status": "active"}).status_code == 404


def test_review_without_a_model_is_the_basic_review(client) -> None:
    add(client, "Alpha Scopes")
    body = client.post("/watch/review").json()
    assert body["mode"] == "basic" and set(body) >= {"summary", "pause", "remove", "add", "regroup", "merge_groups"}


def test_review_failure_is_a_502(client, monkeypatch) -> None:
    def boom(engine, settings):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(watch_manage.review, "review", boom)
    assert client.post("/watch/review").status_code == 502


def test_apply_changes_exactly_the_ticked_proposals(client) -> None:
    a = add(client, "Alpha Scopes")
    b = add(client, "Beta Vision")
    c = add(client, "Gamma Labs", "AI labs")
    body = client.post("/watch/review/apply", json={
        "pause": [a["id"]], "remove": [b["id"]],
        "regroup": [{"id": c["id"], "to": "Labs"}],
        "merge_groups": [{"from": "Endoscopy AI", "to": "Labs"}],
        "add": [{"name": "Newco", "kind": "lab", "category": "Labs", "why": "Keeps appearing.", "query": ""}],
    })
    assert body.status_code == 200
    data = body.json()
    assert data["applied"] == {"paused": 1, "removed": 1, "added": 1, "regrouped": 1, "merged": 1}
    assert [e["name"] for e in data["removed"]] == ["Beta Vision"]
    labs = group(data, "Labs")
    assert {e["name"] for e in labs["entities"]} == {"Alpha Scopes", "Gamma Labs", "Newco"}
    assert next(e for e in labs["entities"] if e["name"] == "Alpha Scopes")["status"] == "muted"


def test_apply_refuses_a_bad_group_name_and_changes_nothing(client) -> None:
    a = add(client, "Alpha Scopes")
    bad = client.post("/watch/review/apply", json={"pause": [a["id"]], "regroup": [{"id": a["id"], "to": "x\ny"}]})
    assert bad.status_code == 422
    assert client.post("/watch/review/apply", json={"add": [{"name": ""}]}).status_code == 422
    with Session(client.engine) as s:
        assert registry.grouped(s)["categories"][0]["entities"][0]["status"] == "active"
