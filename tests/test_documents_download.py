"""Tests for the disk-download path (fetch_document): saving a bookmark's document
to disk and extracting its text. Split out of test_documents.py alongside the
documents_download.py module extraction."""

from pathlib import Path

import httpx

from spyglass_service.documents import fetch_document


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_html_page_is_saved_and_stripped_to_text(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><body><h1>Title</h1><p>Body text</p></body></html>")

    result = fetch_document("https://example.test/article", tmp_path, client=client_for(handler))
    assert Path(result["path"]).suffix == ".html"
    assert "Title Body text" in result["text"]


def test_pdf_is_saved_and_text_extracted(tmp_path: Path) -> None:
    pdf_bytes = b"%PDF-1.4 fake"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes)

    result = fetch_document(
        "https://example.test/paper.pdf", tmp_path,
        client=client_for(handler), pdf_extractor=lambda p: "extracted pdf text",
    )
    saved = Path(result["path"])
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == pdf_bytes
    assert result["text"] == "extracted pdf text"


def test_failed_download_raises(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    try:
        fetch_document("https://example.test/missing", tmp_path, client=client_for(handler))
        raise AssertionError("expected an error")
    except Exception as exc:  # noqa: BLE001
        assert "404" in str(exc) or "document" in str(exc).lower()
