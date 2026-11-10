"""Tests for the Recategorize REST surface.

The kick endpoint is fire-and-forget (like /api/refresh): on an empty DB the background pass
completes instantly and never calls the LLM (no cluster forms), so these tests stay offline.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Item, RunLog


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings))


def seed_card(client: TestClient, ext: str, title: str) -> int:
    engine = client.app.state.engine
    with Session(engine) as session:
        item = Item(source="rss", external_id=ext, title=title, url=f"https://x.test/{ext}")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def test_kick_returns_started(tmp_path: Path) -> None:
    """POST /api/recategorize accepts the job and reports it started (202)."""
    with make_client(tmp_path) as client:
        resp = client.post("/api/recategorize")
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_kick_guarded_when_already_running(tmp_path: Path) -> None:
    """A second kick while a run is in flight is refused (idempotent guard)."""
    with make_client(tmp_path) as client:
        with Session(client.app.state.engine) as session:
            session.add(RunLog(source="recategorize", status="running"))
            session.commit()
        resp = client.post("/api/recategorize")
    assert resp.json()["status"] == "already_running"


def test_kick_refused_when_db_degraded(tmp_path: Path) -> None:
    """A degraded DB refuses the pass (never write to a malformed DB)."""
    with make_client(tmp_path) as client:
        client.app.state.db_ok = False
        resp = client.post("/api/recategorize")
    assert resp.status_code == 409


def test_get_none_before_any_run(tmp_path: Path) -> None:
    """GET /api/recategorize reports 'none' with no candidates before the pass has ever run."""
    with make_client(tmp_path) as client:
        resp = client.get("/api/recategorize")
    assert resp.json() == {"status": "none", "candidates": []}


def test_get_returns_last_run_candidates(tmp_path: Path) -> None:
    """GET surfaces the most recent run's status, assigned count, and candidate list."""
    detail = json.dumps(
        {
            "assigned": 3,
            "candidates": [
                {"suggested_name": "Robotics", "size": 9, "card_ids": [1, 2], "examples": ["A"]}
            ],
        }
    )
    with make_client(tmp_path) as client:
        with Session(client.app.state.engine) as session:
            session.add(
                RunLog(source="recategorize", status="ok", detail=detail,
                       finished_at=datetime.now(UTC))
            )
            session.commit()
        resp = client.get("/api/recategorize").json()
    assert resp["status"] == "ok"
    assert resp["assigned"] == 3
    assert resp["candidates"][0]["suggested_name"] == "Robotics"


def test_accept_creates_category_and_assigns_cards(tmp_path: Path) -> None:
    """POST /api/recategorize/accept registers the category and files the cluster's cards."""
    with make_client(tmp_path) as client:
        c1 = seed_card(client, ext="a", title="One")
        c2 = seed_card(client, ext="b", title="Two")
        resp = client.post(
            "/api/recategorize/accept", json={"name": "New Bucket", "card_ids": [c1, c2]}
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": "New Bucket", "assigned": 2}
        cats = {c["name"] for c in client.get("/api/categories").json()}
        card = next(c for c in client.get("/api/cards").json() if c["id"] == c1)
    assert "New Bucket" in cats
    assert card["category"] == "New Bucket"


def test_accept_rejects_blank_name(tmp_path: Path) -> None:
    """A blank category name is rejected (422) -- never register an empty bucket."""
    with make_client(tmp_path) as client:
        resp = client.post("/api/recategorize/accept", json={"name": "   ", "card_ids": []})
    assert resp.status_code == 422
