"""Tests for the search + full-text REST endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.content_store import store_fulltext
from spyglass_service.models import Card, Item


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings))


def seed_card(client: TestClient, *, title: str, body: str | None) -> int:
    """Insert an item + card; optionally store full text. Return the card id."""
    engine = client.app.state.engine
    with Session(engine) as session:
        item = Item(source="rss", external_id=title, title=title, url="https://x.test/a")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        item_id, card_id = item.id, card.id
    if body is not None:
        store_fulltext(engine, item_id=item_id, markdown=body, source_url="u", content_type="text/html", status="ok")
    return card_id


def test_search_returns_cards_with_snippets(tmp_path: Path) -> None:
    """A full-text match returns the card joined with its item plus a snippet."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client, title="Agent memory", body="Hierarchical memory eviction policy matters.")
        results = client.get("/api/search", params={"q": "eviction"}).json()
    assert len(results) == 1
    assert results[0]["id"] == card_id
    assert "title" in results[0]
    assert "eviction" in results[0]["snippet"].lower()


def test_search_empty_query_returns_empty(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        seed_card(client, title="Agent memory", body="something")
        assert client.get("/api/search", params={"q": ""}).json() == []


def test_get_card_fulltext_returns_stored_markdown(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        card_id = seed_card(client, title="A", body="# Stored body")
        data = client.get(f"/api/cards/{card_id}/fulltext").json()
    assert data["status"] == "ok"
    assert data["markdown"] == "# Stored body"


def test_get_card_fulltext_absent_is_handled(tmp_path: Path) -> None:
    """A card with no stored content reports 'absent', not an error."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client, title="A", body=None)
        data = client.get(f"/api/cards/{card_id}/fulltext").json()
    assert data["status"] == "absent"
    assert data["markdown"] is None


def test_get_card_fulltext_unknown_card_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/cards/9999/fulltext").status_code == 404


def test_post_card_fulltext_queues_a_job(tmp_path: Path) -> None:
    """POST /fulltext records a queued job instead of returning an enrichment result.

    The acquisition ladder can take 30-60s on the browser tier, so the request
    no longer waits for it. The end-to-end POST -> worker -> enrich_item path is covered
    in test_api_content.py.
    """
    with make_client(tmp_path) as client:
        card_id = seed_card(client, title="A", body=None)
        r = client.post(f"/api/cards/{card_id}/fulltext")
    assert r.status_code == 202
    posted = r.json()
    assert posted["status"] == "queued"
    assert posted["card_id"] == card_id


def test_post_card_fulltext_unknown_card_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/cards/9999/fulltext").status_code == 404
