# ruff: noqa: F811
"""Tests for GET /feed/related."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.radar.api import feed_search as api

from .test_assist_support import db  # noqa: F401
from .test_feed_search import FakeIndex, make_item


class State:
    """Stands in for the app's service state."""

    def __init__(self, index) -> None:
        """Hold the index (or an exception to raise)."""
        self.index = index

    def ensure_index(self):
        """The index, or raise when asked to simulate a broken one."""
        if isinstance(self.index, Exception):
            raise self.index
        return self.index


@pytest.fixture
def env(db):
    """A small app with only this router, plus the ids of a few items."""
    index = FakeIndex()
    with Session(db) as session:
        ids = {
            "a": make_item(session, index, "Capsule endoscopy with AI triage", topic="capsule"),
            "b": make_item(session, index, "Capsule review", topic="capsule", age_days=10),
            "c": make_item(session, index, "Robot assisted surgery", topic="robot"),
            "out": make_item(session, index, "Capsule ruled out", tier="out", topic="capsule"),
        }
    app = FastAPI()
    app.include_router(api.router, prefix="/api/radar")
    app.state.engine = db
    app.state.service_state = State(index)
    return app, TestClient(app), ids


def test_text_query_returns_items_with_match_scores(env):
    _app, client, ids = env
    body = client.get("/api/radar/feed/related", params={"text": "capsule endoscopy"}).json()
    assert body["query"] == {"text": "capsule endoscopy"}
    found = [i["id"] for i in body["items"]]
    assert found[:2] == [ids["a"], ids["b"]] and ids["out"] not in found and ids["c"] not in found
    assert all(0 <= i["match"] <= 1 and i["headline"] for i in body["items"])
    assert body["items"][0]["match"] >= body["items"][1]["match"]


def test_item_query_excludes_the_item_and_respects_limit(env):
    _app, client, ids = env
    body = client.get("/api/radar/feed/related", params={"item_id": ids["a"]}).json()
    assert body["query"]["item_id"] == ids["a"] and body["query"]["headline"]
    assert [i["id"] for i in body["items"]] == [ids["b"]]
    limited = client.get("/api/radar/feed/related",
                         params={"text": "capsule", "limit": 1}).json()
    assert len(limited["items"]) == 1


def test_exactly_one_of_text_and_item_id_is_required(env):
    _app, client, ids = env
    assert client.get("/api/radar/feed/related").status_code == 422
    assert client.get("/api/radar/feed/related", params={"text": "  "}).status_code == 422
    both = client.get("/api/radar/feed/related", params={"text": "x", "item_id": ids["a"]})
    assert both.status_code == 422
    assert client.get("/api/radar/feed/related", params={"text": "x" * 301}).status_code == 422
    assert client.get("/api/radar/feed/related", params={"limit": 0, "text": "x"}).status_code == 422


def test_unknown_item_is_404(env):
    _app, client, _ids = env
    assert client.get("/api/radar/feed/related", params={"item_id": 9999}).status_code == 404


def test_cross_site_requests_are_refused(env):
    _app, client, _ids = env
    refused = client.get("/api/radar/feed/related", params={"text": "capsule"},
                         headers={"Sec-Fetch-Site": "cross-site"})
    assert refused.status_code == 403
    same = client.get("/api/radar/feed/related", params={"text": "capsule"},
                      headers={"Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 200


def test_broken_index_still_answers_text_queries_and_gives_nothing_for_items(env):
    app, client, ids = env
    app.state.service_state = State(RuntimeError("no model"))
    body = client.get("/api/radar/feed/related", params={"text": "capsule endoscopy"}).json()
    assert ids["a"] in [i["id"] for i in body["items"]]
    by_item = client.get("/api/radar/feed/related", params={"item_id": ids["a"]}).json()
    assert by_item["items"] == []


def test_the_module_is_mounted_in_the_router():
    from spyglass_service.radar.api import MODULES, build_router

    assert "feed_search" in MODULES
    assert any(r.path == "/api/radar/feed/related" for r in build_router().routes)


def test_items_by_id_keep_the_order_and_skip_unknown_ids(env):
    _app, client, ids = env
    wanted = f"{ids['c']},9999,{ids['a']},{ids['c']}"
    body = client.get("/api/radar/feed/items", params={"ids": wanted}).json()
    assert [i["id"] for i in body["items"]] == [ids["c"], ids["a"]]
    assert body["items"][0]["headline"]


def test_items_by_id_reject_bad_input_and_cross_site(env):
    _app, client, ids = env
    for bad in ("", "x,1", "0", "-3", ",".join(str(n) for n in range(1, 52))):
        assert client.get("/api/radar/feed/items", params={"ids": bad}).status_code == 422, bad
    assert client.get("/api/radar/feed/items").status_code == 422
    refused = client.get("/api/radar/feed/items", params={"ids": str(ids["a"])},
                         headers={"Sec-Fetch-Site": "cross-site"})
    assert refused.status_code == 403
