"""Tests for the tracks endpoints, on an app that mounts only the tracks router."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.radar.api import tracks as tracks_api
from spyglass_service.radar.capture import CaptureError
from spyglass_service.radar.models import ItemExtra, dumps
from spyglass_service.radar.profile import get_profile

from .test_brief_seed import add_item, make_engine, make_index

SUGGESTION = {"suggestions": [{
    "label": "Computer-aided detection in colonoscopy", "query": '"computer-aided detection"',
    "kind": "topic", "section": "health", "why": "the technique described",
}]}


class FakeState:
    """Stand-in for the service state that hands out a prepared index."""

    def __init__(self, index) -> None:
        self.index = index

    def ensure_index(self):
        """The prepared index."""
        return self.index


@pytest.fixture
def env(tmp_path, monkeypatch):
    """(client, engine, ids) with a stub model, no real search and a three-item index."""
    engine = make_engine(tmp_path)
    base = add_item(engine, "FDA clears a colonoscopy AI tool", entities=["Acme Health"])
    near = add_item(engine, "Another colonoscopy tool", entities=[])
    index = make_index({base: [1, 0, 0, 0], near: [0.9, 0.1, 0, 0]})
    app = FastAPI()
    app.include_router(tracks_api.router)
    app.state.engine = engine
    app.state.settings = SimpleNamespace()
    app.state.service_state = FakeState(index)
    monkeypatch.setattr(tracks_api, "make_llm", lambda settings: (lambda m, s: SUGGESTION))
    monkeypatch.setattr(tracks_api, "run_track_now", lambda e, s, track: 4)
    with TestClient(app) as client:
        yield client, engine, {"base": base, "near": near}
    engine.dispose()


def body(**overrides) -> dict:
    """A valid create request."""
    return {"label": "Capsule endoscopy AI", "query": '"capsule endoscopy" AI',
            "section": "health", "kind": "topic", **overrides}


def test_suggest_for_item_returns_suggestions_and_similar_items(env) -> None:
    client, _, ids = env
    response = client.post(f"/items/{ids['base']}/track/suggest")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "ai"
    assert set(data["suggestions"][0]) == {"label", "query", "kind", "section", "section_label",
                                           "why", "already_followed"}
    assert [i["id"] for i in data["similar"]] == [ids["near"]]


def test_suggest_without_a_model_still_answers(env, monkeypatch) -> None:
    client, _, ids = env
    monkeypatch.setattr(tracks_api, "make_llm", lambda settings: None)
    data = client.post(f"/items/{ids['base']}/track/suggest").json()
    assert data["mode"] == "basic" and data["suggestions"][0]["label"] == "Acme Health"


def test_suggest_for_unknown_item_is_404(env) -> None:
    assert env[0].post("/items/9999/track/suggest").status_code == 404


def test_suggest_for_url_captures_reads_and_returns_the_item(env, monkeypatch) -> None:
    client, _, ids = env
    calls = []
    monkeypatch.setattr(tracks_api, "capture_url",
                        lambda engine, settings, url, via: calls.append((url, via)) or ids["base"])
    monkeypatch.setattr(tracks_api, "ensure_reader_doc",
                        lambda engine, settings, item_id: calls.append(item_id))
    data = client.post("/track/suggest", json={"url": " https://example.com/a "}).json()
    assert calls == [("https://example.com/a", "manual"), ids["base"]]
    assert data["item"]["id"] == ids["base"] and data["suggestions"] and "similar" in data


def test_suggest_for_url_maps_capture_errors_to_422_and_survives_a_reader_failure(env, monkeypatch) -> None:
    client, _, ids = env

    def refuse(engine, settings, url, via):
        raise CaptureError("That address is not public.")

    monkeypatch.setattr(tracks_api, "capture_url", refuse)
    refused = client.post("/track/suggest", json={"url": "http://10.0.0.1/"})
    assert refused.status_code == 422 and refused.json()["detail"] == "That address is not public."
    assert client.post("/track/suggest", json={"url": ""}).status_code == 422

    def unreadable(engine, settings, item_id):
        raise RuntimeError("fetch blew up")

    monkeypatch.setattr(tracks_api, "capture_url", lambda *a, **k: ids["base"])
    monkeypatch.setattr(tracks_api, "ensure_reader_doc", unreadable)
    assert client.post("/track/suggest", json={"url": "https://example.com/x"}).status_code == 200


def test_follow_creates_the_track_adds_the_topic_and_reports_new_items(env) -> None:
    client, engine, ids = env
    response = client.post("/tracks", json=body(from_item_id=ids["base"]))
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1 and data["new_items"] == 4 and data["section_label"]
    assert data["from_item_id"] == ids["base"] and data["active"] is True
    with Session(engine) as session:
        names = [t["name"] for t in get_profile(session)["topics"]]
    assert names.count("Capsule endoscopy AI") == 1


def test_follow_survives_a_failing_first_search(env, monkeypatch) -> None:
    client, _, _ = env
    monkeypatch.undo()  # use the real run_track_now, whose search is made to fail below
    from spyglass_service.radar.sources import news_search

    def explode(*args, **kwargs):
        raise RuntimeError("all queries failed")

    monkeypatch.setattr(news_search, "collect_news", explode)
    response = client.post("/tracks", json=body())
    assert response.status_code == 201 and response.json()["new_items"] == 0


def test_follow_conflict_and_validation_failures(env) -> None:
    client, _, _ = env
    assert client.post("/tracks", json=body()).status_code == 201
    assert client.post("/tracks", json=body(label="capsule endoscopy ai")).status_code == 409
    bad = [body(label=""), body(label="x" * 81), body(query="q" * 201), body(query="a\nb"),
           body(label="bell\x07"), body(section="nope"), body(kind="planet"),
           body(from_item_id=9999), {"label": "only a label"}]
    for payload in bad:
        assert client.post("/tracks", json=payload).status_code == 422, payload
    assert len(client.get("/tracks").json()["tracks"]) == 1


def test_list_shows_section_label_and_the_three_newest_recent_items(env) -> None:
    client, engine, _ = env
    client.post("/tracks", json=body())
    ids = [add_item(engine, f"Capsule story {n}", age_hours=n + 1) for n in range(5)]
    with Session(engine) as session:
        for item_id in ids:
            session.add(ItemExtra(item_id=item_id, data=dumps({"query": '"capsule endoscopy" AI'})))
        session.commit()
    track = client.get("/tracks").json()["tracks"][0]
    assert track["section_label"] == "Healthcare AI & medtech"
    assert [i["title"] for i in track["recent"]] == [f"Capsule story {n}" for n in range(3)]
    assert client.get("/tracks").json()["tracks"][0]["last_new"] == 0


def test_list_is_empty_at_first(env) -> None:
    assert env[0].get("/tracks").json() == {"tracks": []}


def test_patch_pauses_renames_and_reports_errors(env) -> None:
    client, _, _ = env
    first = client.post("/tracks", json=body()).json()["id"]
    second = client.post("/tracks", json=body(label="Other subject", query="other")).json()["id"]
    paused = client.patch(f"/tracks/{first}", json={"active": False}).json()
    assert paused["active"] is False and paused["recent"] == []
    assert client.patch(f"/tracks/{first}", json={"label": "Renamed", "section": "agents"}
                        ).json()["section"] == "agents"
    assert client.patch(f"/tracks/{second}", json={"label": "renamed"}).status_code == 409
    assert client.patch(f"/tracks/{second}", json={"section": "nope"}).status_code == 422
    assert client.patch(f"/tracks/{second}", json={}).status_code == 422
    assert client.patch(f"/tracks/{second}", json={"label": "a\x00b"}).status_code == 422
    assert client.patch("/tracks/99", json={"active": True}).status_code == 404


def test_delete_removes_the_track_and_its_topic(env) -> None:
    client, engine, _ = env
    track_id = client.post("/tracks", json=body()).json()["id"]
    assert client.delete(f"/tracks/{track_id}").json() == {"deleted": track_id}
    assert client.get("/tracks").json() == {"tracks": []}
    with Session(engine) as session:
        assert "Capsule endoscopy AI" not in [t["name"] for t in get_profile(session)["topics"]]
    assert client.delete(f"/tracks/{track_id}").status_code == 404
