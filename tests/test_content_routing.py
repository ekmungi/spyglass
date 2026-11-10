"""Tests for the content-type classifier: pre-fetch URL routing +
post-fetch byte-sniff tiebreaker. Pure functions, no network."""

from spyglass_service.content_routing import classify_url, sniff_kind


# --- classify_url: pre-fetch signals -------------------------------------------------


def test_classify_url_youtube_watch_is_transcript() -> None:
    assert classify_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "transcript"


def test_classify_url_youtube_shorts_is_transcript() -> None:
    assert classify_url("https://www.youtube.com/shorts/abc123") == "transcript"


def test_classify_url_youtube_live_is_transcript() -> None:
    assert classify_url("https://www.youtube.com/live/abc123") == "transcript"


def test_classify_url_youtu_be_short_link_is_transcript() -> None:
    assert classify_url("https://youtu.be/dQw4w9WgXcQ") == "transcript"


def test_classify_url_vimeo_is_transcript() -> None:
    assert classify_url("https://vimeo.com/76979871") == "transcript"


def test_classify_url_pdf_extension_is_pdf() -> None:
    assert classify_url("https://example.test/paper.pdf") == "pdf"


def test_classify_url_pdf_extension_with_query_string_is_pdf() -> None:
    assert classify_url("https://example.test/paper.pdf?download=1") == "pdf"


def test_classify_url_image_extensions_are_image() -> None:
    for ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "svg"):
        assert classify_url(f"https://example.test/pic.{ext}") == "image", ext


def test_classify_url_generic_page_returns_none() -> None:
    """No pre-fetch signal -- conductor defaults to html and refines post-fetch."""
    assert classify_url("https://example.test/article") is None


def test_classify_url_non_video_youtube_page_returns_none() -> None:
    """A youtube.com URL that isn't a recognized video pattern (e.g. the homepage)
    has no pre-fetch signal."""
    assert classify_url("https://www.youtube.com/") is None


# --- sniff_kind: post-fetch tiebreaker -------------------------------------------------


def test_sniff_kind_pdf_content_type() -> None:
    assert sniff_kind("application/pdf", b"%PDF-1.4 ...") == "pdf"


def test_sniff_kind_image_content_type() -> None:
    assert sniff_kind("image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 40) == "image"


def test_sniff_kind_html_content_type() -> None:
    assert sniff_kind("text/html", b"<html><body>hi</body></html>") == "html"


def test_sniff_kind_xhtml_content_type_is_html() -> None:
    assert sniff_kind("application/xhtml+xml", b"<html/>") == "html"


def test_sniff_kind_octet_stream_with_pdf_magic_is_corrected_to_pdf() -> None:
    """A mislabeled PDF (served as application/octet-stream) is corrected by the
    byte-sniff -- the bytes are ground truth over an ambiguous/wrong header."""
    assert sniff_kind("application/octet-stream", b"%PDF-1.4 fake pdf body") == "pdf"


def test_sniff_kind_octet_stream_with_image_magic_is_corrected_to_image() -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 40
    assert sniff_kind("application/octet-stream", png_bytes) == "image"


def test_sniff_kind_octet_stream_with_no_recognizable_magic_defaults_html() -> None:
    assert sniff_kind("application/octet-stream", b"just some plain bytes here") == "html"


def test_sniff_kind_empty_content_type_falls_back_to_sniff() -> None:
    assert sniff_kind("", b"%PDF-1.4 fake pdf body") == "pdf"


def test_sniff_kind_empty_content_type_and_empty_bytes_defaults_html() -> None:
    """No header AND no bytes to sniff -- default to html (never crash on empty input)."""
    assert sniff_kind("", b"") == "html"


def test_sniff_kind_missing_content_type_and_short_bytes_defaults_html() -> None:
    assert sniff_kind("application/octet-stream", b"") == "html"
