"""Tests for PDF support: notice documents, the download cache, size cap and address checks."""

from pathlib import Path

import httpx
import pytest

from spyglass_service.radar.reader.pdf import (
    MAX_PDF_BYTES, PdfError, cache_path, download_pdf, ensure_pdf, is_public_http_url, pdf_result,
)

_PDF = b"%PDF-1.4\n" + b"x" * 100


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_pdf_result_has_notice_abstract_and_alt_url() -> None:
    result = pdf_result("https://x.org/a.pdf", "T", "Para one.\n\nPara <two>.", notice="Shown as PDF.",
                        source_url="https://x.org/abs")
    assert result["kind"] == "pdf" and result["alt_url"] == "https://x.org/a.pdf"
    assert "Shown as PDF." in result["html"] and "<h2>Abstract</h2>" in result["html"]
    assert "&lt;two&gt;" in result["html"]


def test_pdf_result_without_abstract_is_only_the_notice() -> None:
    result = pdf_result("u", "T", "", notice="Shown as PDF.", source_url="s")
    assert "Abstract" not in result["html"]


def test_download_writes_a_valid_pdf(tmp_path: Path) -> None:
    dest = tmp_path / "pdf_cache" / "1.pdf"
    download_pdf("https://example.com/a.pdf", dest, client=_client(lambda r: httpx.Response(200, content=_PDF)))
    assert dest.read_bytes() == _PDF
    assert not dest.with_suffix(".part").exists()


def test_download_rejects_non_pdf_content(tmp_path: Path) -> None:
    dest = tmp_path / "1.pdf"
    with pytest.raises(PdfError, match="did not return a PDF"):
        download_pdf("https://example.com/a.pdf", dest,
                     client=_client(lambda r: httpx.Response(200, content=b"<html>")))
    assert not dest.exists() and not dest.with_suffix(".part").exists()


def test_download_rejects_http_errors(tmp_path: Path) -> None:
    with pytest.raises(PdfError, match="404"):
        download_pdf("https://example.com/a.pdf", tmp_path / "1.pdf",
                     client=_client(lambda r: httpx.Response(404)))


def test_download_enforces_the_size_cap_from_the_header(tmp_path: Path) -> None:
    headers = {"content-length": str(MAX_PDF_BYTES + 1)}
    with pytest.raises(PdfError, match="150 MB"):
        download_pdf("https://example.com/a.pdf", tmp_path / "1.pdf",
                     client=_client(lambda r: httpx.Response(200, content=_PDF, headers=headers)))


def test_download_enforces_the_size_cap_while_streaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("spyglass_service.radar.reader.pdf.MAX_PDF_BYTES", 1000)
    dest = tmp_path / "1.pdf"
    with pytest.raises(PdfError, match="larger than"):
        download_pdf("https://example.com/a.pdf", dest,
                     client=_client(lambda r: httpx.Response(200, content=b"%PDF" + b"x" * 5000)))
    assert not dest.exists() and not dest.with_suffix(".part").exists()


def test_download_wraps_transport_errors(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(PdfError, match="Could not download"):
        download_pdf("https://example.com/a.pdf", tmp_path / "1.pdf", client=_client(boom))


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/a.pdf", "http://localhost/a.pdf", "http://127.0.0.1/a.pdf",
    "http://192.168.1.5/a.pdf", "http://[::1]/a.pdf", "http:///a",
])
def test_non_public_addresses_are_refused(url: str, tmp_path: Path) -> None:
    assert not is_public_http_url(url)
    with pytest.raises(PdfError):
        download_pdf(url, tmp_path / "1.pdf", client=_client(lambda r: httpx.Response(200, content=_PDF)))


def test_public_addresses_are_allowed() -> None:
    assert is_public_http_url("https://arxiv.org/pdf/2401.00001")
    assert is_public_http_url("http://example.com/a.pdf")


def test_ensure_pdf_downloads_once_then_uses_the_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def downloader(url: str, dest: Path) -> None:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_PDF)

    first = ensure_pdf(tmp_path, 7, "https://example.com/a.pdf", downloader=downloader)
    second = ensure_pdf(tmp_path, 7, "https://example.com/a.pdf", downloader=downloader)
    assert first == second == cache_path(tmp_path, 7)
    assert calls == ["https://example.com/a.pdf"]


# ---- cache bound -----------------------------------------------------------------------------


def _fill(directory: Path, name: str, size: int, age: int) -> Path:
    """A cached file of `size` bytes last used `age` seconds ago."""
    import os
    import time

    path = directory / name
    path.write_bytes(b"x" * size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_prune_cache_deletes_least_recently_used_files_until_under_the_limit(tmp_path: Path) -> None:
    from spyglass_service.radar.reader.pdf import prune_cache

    cache = tmp_path / "pdf_cache"
    cache.mkdir()
    oldest = _fill(cache, "1.pdf", 400, age=300)
    middle = _fill(cache, "2.pdf", 400, age=200)
    newest = _fill(cache, "3.pdf", 400, age=100)
    removed = prune_cache(tmp_path, max_bytes=900)
    assert removed == 1 and not oldest.exists() and middle.exists() and newest.exists()


def test_prune_cache_keeps_the_file_just_written_even_when_it_alone_exceeds_the_limit(tmp_path: Path) -> None:
    from spyglass_service.radar.reader.pdf import prune_cache

    cache = tmp_path / "pdf_cache"
    cache.mkdir()
    older = _fill(cache, "1.pdf", 300, age=50)
    fresh = _fill(cache, "2.pdf", 600, age=1)
    prune_cache(tmp_path, max_bytes=500, keep=fresh)
    assert fresh.exists() and not older.exists()


def test_prune_cache_ignores_a_missing_folder_and_unrelated_files(tmp_path: Path) -> None:
    from spyglass_service.radar.reader.pdf import prune_cache

    assert prune_cache(tmp_path, max_bytes=1) == 0
    (tmp_path / "pdf_cache").mkdir()
    note = tmp_path / "pdf_cache" / "notes.txt"
    note.write_text("keep me")
    assert prune_cache(tmp_path, max_bytes=0) == 0 and note.exists()


def test_ensure_pdf_prunes_after_a_download_and_marks_a_cache_hit_as_recently_used(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from spyglass_service.radar.reader import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "MAX_CACHE_BYTES", 250)
    cache = tmp_path / "pdf_cache"
    cache.mkdir()
    old = _fill(cache, "1.pdf", 200, age=1000)
    hit = _fill(cache, "2.pdf", 20, age=900)
    before = hit.stat().st_mtime
    ensure_pdf(tmp_path, 2, "https://x.org/p.pdf", downloader=lambda url, dest: pytest.fail("cached"))
    assert hit.stat().st_mtime > before  # a cache hit counts as use

    def downloader(url: str, dest: Path) -> None:
        dest.write_bytes(b"y" * 100)

    ensure_pdf(tmp_path, 3, "https://x.org/q.pdf", downloader=downloader)
    assert not old.exists() and hit.exists() and (cache / "3.pdf").exists()
    assert os.path.getsize(cache / "3.pdf") == 100


def test_download_guards_the_client_it_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spyglass_service.radar.reader import pdf as pdf_mod

    built = _client(lambda request: httpx.Response(200, content=_PDF, headers={"content-type": "application/pdf"}))
    monkeypatch.setattr(pdf_mod, "build_client", lambda: built)
    assert not built.event_hooks["request"]
    # `download_pdf` closes the client it built, so look at the hooks it installed from inside a request.
    seen: list[int] = []
    original = built.send

    def spy(request, **kwargs):
        seen.append(len(built.event_hooks["request"]))
        return original(request, **kwargs)

    monkeypatch.setattr(built, "send", spy)
    download_pdf("https://x.org/p.pdf", tmp_path / "a.pdf")
    assert seen and seen[0] >= 1
