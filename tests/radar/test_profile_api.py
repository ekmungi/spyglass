"""Tests for the profile endpoints, on a small app that mounts only the profile router."""

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.radar.api import profile as profile_api
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE

from .test_assess_support import add_item, make_engine, set_state


@pytest.fixture()
def setup(tmp_path):
    """(client, engine) for an app with only the profile router under /api/radar."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(profile_api.router, prefix="/api/radar")
    app.state.engine = engine
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def test_get_profile_returns_profile_and_examples(setup) -> None:
    """GET returns the default profile and examples derived from history."""
    client, engine = setup
    liked = add_item(engine, "A saved article about endoscopy AI")
    set_state(engine, liked, vote="more")
    # Only items the radar judged into a profile section may become examples.
    with Session(engine) as session:
        session.add(Assessment(item_id=liked, section="health", tier="notable", score=70))
        session.commit()
    client.app.state.settings = Settings(_env_file=None, privacy_send_examples=True)
    body = client.get("/api/radar/profile").json()
    assert body["profile"]["sections"] == DEFAULT_PROFILE["sections"]
    assert body["examples"] == {"liked": ["A saved article about endoscopy AI"], "disliked": []}


def test_put_profile_saves_and_bumps_version(setup) -> None:
    """PUT stores the document with the next version and GET then returns it."""
    client, _engine = setup
    doc = copy.deepcopy(DEFAULT_PROFILE)
    doc["statement"] = "A changed statement."
    response = client.put("/api/radar/profile", json=doc)
    assert response.status_code == 200
    assert response.json()["profile"]["version"] == DEFAULT_PROFILE["version"] + 1
    assert client.get("/api/radar/profile").json()["profile"]["statement"] == "A changed statement."


@pytest.mark.parametrize("change", [
    {"statement": ""},
    {"sections": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]},
    {"topics": [{"name": "X", "section": "missing"}]},
])
def test_put_profile_rejects_invalid_documents(setup, change: dict) -> None:
    """A malformed document is refused with 422 and nothing is stored."""
    client, _engine = setup
    response = client.put("/api/radar/profile", json={**copy.deepcopy(DEFAULT_PROFILE), **change})
    assert response.status_code == 422
    assert client.get("/api/radar/profile").json()["profile"]["version"] == DEFAULT_PROFILE["version"]


def test_put_profile_maps_a_save_error_to_422(setup, monkeypatch) -> None:
    """A ProfileError raised while saving becomes a 422 with its message."""
    client, _engine = setup

    def refuse(_session, _doc):
        """Reject every save."""
        raise profile_api.ProfileError("statement: too vague")

    monkeypatch.setattr(profile_api, "save_profile", refuse)
    response = client.put("/api/radar/profile", json=copy.deepcopy(DEFAULT_PROFILE))
    assert response.status_code == 422 and response.json()["detail"] == "statement: too vague"
