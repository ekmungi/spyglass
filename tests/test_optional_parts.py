"""The optional parts setup may leave out: PDF reading (PyMuPDF) and the local AI model (fastembed).

Each test blocks the library's import, as an install without that part has it, and checks that
Spyglass still works: PDFs are read with pypdf, embedding is reported as not installed, and the
Settings page can say what is missing and how to add it.
"""

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service import capabilities
from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.embeddings import (
    ARCTIC_DIM,
    ARCTIC_MODEL,
    EmbeddingIndex,
    embed_pending,
    fastembed_embedder,
)
from spyglass_service.extractors.pdf import extract_pdf
from spyglass_service.models import Card, Item


def _block(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make `import name` fail for each name, as on a PC where setup left that part out."""
    for name in names:
        for loaded in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
            monkeypatch.delitem(sys.modules, loaded)
        monkeypatch.setitem(sys.modules, name, None)


def _pdf_with_text(text: str) -> bytes:
    """A one-page PDF holding `text`, made with PyMuPDF before any import is blocked."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    out = io.BytesIO(doc.tobytes())
    doc.close()
    return out.getvalue()


def test_both_parts_report_installed_in_the_full_environment() -> None:
    assert capabilities.pdf_reading_full() is True
    assert capabilities.local_ai_installed() is True


def test_parts_report_missing_when_their_import_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _block(monkeypatch, "fitz", "pymupdf", "fastembed")
    assert capabilities.pdf_reading_full() is False
    assert capabilities.local_ai_installed() is False


def test_pdf_is_read_with_pypdf_without_pymupdf(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _pdf_with_text("Spyglass reads this page")
    _block(monkeypatch, "fitz", "pymupdf")
    assert "Spyglass reads this page" in extract_pdf(content)


def test_unreadable_pdf_gives_empty_text_without_pymupdf(monkeypatch: pytest.MonkeyPatch) -> None:
    _block(monkeypatch, "fitz", "pymupdf")
    assert extract_pdf(b"not a pdf at all") == ""


def test_embedding_without_the_model_says_it_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _block(monkeypatch, "fastembed")
    embed = fastembed_embedder()
    with pytest.raises(capabilities.LocalModelMissing, match="local AI model is not installed"):
        embed(["a text"])


def test_embed_pending_skips_quietly_without_the_model(engine) -> None:
    """The background pass embeds nothing and raises nothing; no half-written rows remain."""
    def missing(_texts: list[str]) -> np.ndarray:
        raise capabilities.LocalModelMissing()

    with Session(engine) as session:
        item = Item(source="rss", external_id="e1", url="https://example.com/a", title="A")
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
        session.add(Card(item_id=item_id, summary="a summary"))
        session.commit()
    index = EmbeddingIndex(missing, ARCTIC_MODEL, ARCTIC_DIM)
    assert embed_pending(engine, index) == 0
    assert not index.has(item_id)


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, started_by="desktop")
    return TestClient(app), app


def test_settings_route_reports_the_full_install(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    try:
        body = client.get("/api/radar/desktop/capabilities").json()
    finally:
        app.state.engine.dispose()
    assert body["pdf_reading"] == "full"
    assert body["local_ai"] is True
    assert body["missing"] == []


def test_settings_route_names_what_is_missing_and_how_to_add_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _block(monkeypatch, "fitz", "pymupdf", "fastembed")
    client, app = _client(tmp_path)
    try:
        body = client.get("/api/radar/desktop/capabilities").json()
    finally:
        app.state.engine.dispose()
    assert body["pdf_reading"] == "basic"
    assert body["local_ai"] is False
    assert [part["id"] for part in body["missing"]] == ["pdf", "local-ai"]
    assert all("setup again" in part["how_to_add"] for part in body["missing"])


def test_a_request_that_needs_the_model_gets_503(tmp_path: Path) -> None:
    """Any route whose work reaches the missing model answers with a plain reason, not a 500."""
    client, app = _client(tmp_path)

    @app.get("/test-only/embed")
    def needs_the_model() -> dict:
        raise capabilities.LocalModelMissing()

    try:
        reply = client.get("/test-only/embed")
    finally:
        app.state.engine.dispose()
    assert reply.status_code == 503
    assert "local AI model is not installed" in reply.json()["detail"]


def test_related_items_fall_back_to_text_without_the_model(tmp_path: Path) -> None:
    """Search by meaning is off; the related-items search still answers from the words."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")

    def missing(_texts: list[str]) -> np.ndarray:
        raise capabilities.LocalModelMissing()

    app = create_app(settings, index=EmbeddingIndex(missing, ARCTIC_MODEL, ARCTIC_DIM),
                     skip_startup_embed=True)
    try:
        with TestClient(app) as client:
            reply = client.get("/api/radar/feed/related", params={"text": "retina imaging"})
    finally:
        app.state.engine.dispose()
    assert reply.status_code == 200
    assert reply.json()["items"] == []
