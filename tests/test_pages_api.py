# tests/test_pages_api.py
"""Tests for POST /api/pages: add an arbitrary web page as a manual item.

The endpoint canonicalizes the URL, dedupes against existing items (returning the
existing card as status=exists), otherwise creates Item+Card, then best-effort enriches
(bypass_gate). Both network seams -- fetch_page_title and enrich_item -- are always
mocked here; their failures must never fail the request.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Item


def _make_client(tmp_path: Path) -> TestClient:
    """TestClient with the startup embed/enrich pass disabled (no background races)."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


@pytest.fixture(autouse=True)
def _mock_network(monkeypatch):
    """Default seams: title fetch returns a page title, enrichment is a recorded no-op."""
    calls = {"enrich": [], "title": []}

    def fake_title(url):
        calls["title"].append(url)
        return "Fetched Page Title"

    def fake_enrich(engine, index, settings, card_id, **kwargs):
        calls["enrich"].append((card_id, kwargs))
        return {"relevance_score": 80, "recommended": True, "summary": "s", "category": None}

    monkeypatch.setattr("spyglass_service.api_pages.fetch_page_title", fake_title)
    monkeypatch.setattr("spyglass_service.api_pages.enrich_item", fake_enrich)
    return calls


def test_post_page_creates_item_and_card(tmp_path, _mock_network):
    """Happy path: a new URL creates Item(source=manual)+Card, enriches gate-free, and
    returns the serialized card with status=created."""
    with _make_client(tmp_path) as client:
        r = client.post("/api/pages", json={"url": "https://example.test/some/post"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "created"
        assert body["title"] == "Fetched Page Title"
        assert body["url"] == "https://example.test/some/post"
        assert body["source"] == "manual"
        assert body["origin"] == "example.test"
        engine = client.app.state.engine
        with Session(engine) as s:
            item = s.exec(select(Item)).one()
            card = s.exec(select(Card)).one()
        assert item.source == "manual"
        assert item.external_id == "https://example.test/some/post"
        assert item.published_at is None and item.feed_url is None
        assert card.item_id == item.id and card.curated is False
    # Enrichment ran once, for this card, with the gate bypassed (explicit user action).
    assert len(_mock_network["enrich"]) == 1
    enriched_id, kwargs = _mock_network["enrich"][0]
    assert enriched_id == card.id
    assert kwargs.get("bypass_gate") is True


def test_post_page_dedupes_by_canonical_url(tmp_path, _mock_network):
    """The same page added twice returns the FIRST item's card as status=exists --
    including via a different-but-canonically-equal URL (arXiv abs vs pdf)."""
    with _make_client(tmp_path) as client:
        first = client.post("/api/pages", json={"url": "https://arxiv.org/abs/2601.00001"}).json()
        assert first["status"] == "created"
        # The canonical form (external_id) is the pdf URL; posting it again dedupes.
        again = client.post("/api/pages", json={"url": "https://arxiv.org/pdf/2601.00001"}).json()
        assert again["status"] == "exists"
        assert again["id"] == first["id"]
        with Session(client.app.state.engine) as s:
            assert len(s.exec(select(Item)).all()) == 1
    assert len(_mock_network["enrich"]) == 1  # only the original create enriched


def test_post_page_dedupe_creates_card_when_item_has_none(tmp_path, _mock_network):
    """An existing card-less item (edge state) gets a card created and returned."""
    with _make_client(tmp_path) as client:
        with Session(client.app.state.engine) as s:
            item = Item(source="rss", external_id="https://x.test/orphan",
                        title="Orphan", url="https://x.test/orphan")
            s.add(item)
            s.commit()
            s.refresh(item)
            item_id = item.id
        r = client.post("/api/pages", json={"url": "https://x.test/orphan"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "exists" and body["title"] == "Orphan"
        with Session(client.app.state.engine) as s:
            card = s.exec(select(Card)).one()
        assert card.item_id == item_id
    assert _mock_network["enrich"] == []  # dedupe never re-enriches


def test_post_page_dedupes_on_item_url_too(tmp_path, _mock_network):
    """An item whose URL (not external_id) matches the canonical form also dedupes."""
    with _make_client(tmp_path) as client:
        with Session(client.app.state.engine) as s:
            item = Item(source="raindrop", external_id="raindrop-123",
                        title="Saved", url="https://x.test/saved")
            s.add(item)
            s.flush()
            s.add(Card(item_id=item.id, summary="s"))
            s.commit()
        body = client.post("/api/pages", json={"url": "https://x.test/saved"}).json()
        assert body["status"] == "exists" and body["title"] == "Saved"


@pytest.mark.parametrize("url", ["ftp://x.test/file", "file:///etc/passwd", "not-a-url", ""])
def test_post_page_rejects_non_http_schemes(tmp_path, url, _mock_network):
    """Anything but http/https is a 400 before any network or DB work."""
    with _make_client(tmp_path) as client:
        r = client.post("/api/pages", json={"url": url})
        assert r.status_code == 400
        with Session(client.app.state.engine) as s:
            assert s.exec(select(Item)).all() == []
    assert _mock_network["title"] == [] and _mock_network["enrich"] == []


def test_post_page_dedupes_raw_url_against_canonicalizing_incoming(tmp_path, _mock_network):
    """A page already stored under its RAW url dedupes even when the incoming URL
    canonicalizes to a different string. An arXiv abs page collected by another source
    keeps url=abs-form; re-adding that abs URL (which normalizes to the pdf form) must
    match on the raw form, not create a second manual card."""
    with _make_client(tmp_path) as client:
        with Session(client.app.state.engine) as s:
            item = Item(source="rss", external_id="arxiv-guid-9",
                        title="Paper", url="https://arxiv.org/abs/2601.09999")
            s.add(item)
            s.flush()
            s.add(Card(item_id=item.id, summary="s"))
            s.commit()
        body = client.post("/api/pages", json={"url": "https://arxiv.org/abs/2601.09999"}).json()
        assert body["status"] == "exists" and body["title"] == "Paper"
        with Session(client.app.state.engine) as s:
            assert len(s.exec(select(Item)).all()) == 1  # no duplicate manual item
    assert _mock_network["enrich"] == []


def test_post_page_enrich_failure_still_returns_the_card(tmp_path, monkeypatch, _mock_network):
    """An enrichment crash must not fail the request -- the card exists and is returned."""

    def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("spyglass_service.api_pages.enrich_item", boom)
    with _make_client(tmp_path) as client:
        r = client.post("/api/pages", json={"url": "https://example.test/fragile"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "created"
        assert body["title"] == "Fetched Page Title"
        with Session(client.app.state.engine) as s:
            assert len(s.exec(select(Card)).all()) == 1


def test_post_page_title_failure_falls_back_to_the_url(tmp_path, monkeypatch, _mock_network):
    """A failed/None title fetch falls back to the URL itself (never an empty title)."""
    monkeypatch.setattr("spyglass_service.api_pages.fetch_page_title", lambda url: None)
    with _make_client(tmp_path) as client:
        body = client.post("/api/pages", json={"url": "https://example.test/untitled"}).json()
        assert body["status"] == "created"
        assert body["title"] == "https://example.test/untitled"


def test_post_page_title_exception_falls_back_to_the_url(tmp_path, monkeypatch, _mock_network):
    """Even a raising title fetcher is tolerated at runtime -- URL fallback, request OK."""

    def boom(url):
        raise RuntimeError("network exploded")

    monkeypatch.setattr("spyglass_service.api_pages.fetch_page_title", boom)
    with _make_client(tmp_path) as client:
        body = client.post("/api/pages", json={"url": "https://example.test/kaboom"}).json()
        assert body["status"] == "created"
        assert body["title"] == "https://example.test/kaboom"
