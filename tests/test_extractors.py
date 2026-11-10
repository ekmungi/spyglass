"""Tests for the extractor layer -- pure content-to-text units used by fetch_fulltext."""

import logging

from spyglass_service.extractors.html import (
    _MIN_PRIMARY_CHARS,
    _readability_fallback,
    extract_markdown,
)
from spyglass_service.extractors.pdf import extract_pdf


def test_extract_markdown_uses_the_injected_extractor() -> None:
    """Extraction delegates to an injectable extractor (real one is trafilatura)."""
    md = extract_markdown("<h1>H</h1><p>p</p>", extractor=lambda _h: "# H\n\np")
    assert md == "# H\n\np"


def test_extract_markdown_returns_empty_string_when_extractor_yields_nothing() -> None:
    """A falsy extractor result (None or '') normalizes to '' (both primary and fallback
    are stubbed to yield nothing, so there is nothing usable to fall back to)."""
    assert (
        extract_markdown("<html></html>", extractor=lambda _h: None, fallback=lambda _h: None)
        == ""
    )


def test_extract_markdown_primary_success_does_not_invoke_fallback() -> None:
    """When the primary (trafilatura) yields ample text, the fallback seam is never
    called -- proves existing behaviour is preserved and the fallback is opt-in-by-need."""

    def _spy_fallback(_html: str) -> str:
        raise AssertionError("fallback must not be called when the primary succeeds")

    ample = ("word " * 100).strip()  # well over _MIN_PRIMARY_CHARS
    md = extract_markdown("<p>ignored</p>", extractor=lambda _h: ample, fallback=_spy_fallback)
    assert md == ample


def test_extract_markdown_falls_back_when_primary_is_empty() -> None:
    """Primary yields '' (e.g. trafilatura defeated by an unusual layout) -> the
    fallback runs and its output is returned."""
    md = extract_markdown(
        "<html></html>",
        extractor=lambda _h: "",
        fallback=lambda _h: "readability rescued this content",
    )
    assert md == "readability rescued this content"


def test_extract_markdown_falls_back_when_primary_is_below_threshold() -> None:
    """Primary yields a short scrap (below _MIN_PRIMARY_CHARS) -> fallback's longer
    output wins."""
    tiny_primary = "x" * (_MIN_PRIMARY_CHARS - 1)
    longer_fallback = "y" * _MIN_PRIMARY_CHARS
    md = extract_markdown(
        "<html></html>", extractor=lambda _h: tiny_primary, fallback=lambda _h: longer_fallback
    )
    assert md == longer_fallback


def test_extract_markdown_keeps_primary_when_fallback_is_not_longer() -> None:
    """Below-threshold primary still wins over an even-shorter (or equal) fallback --
    "MORE usable text" is the tie-breaker, not "fallback ran at all"."""
    tiny_primary = "x" * (_MIN_PRIMARY_CHARS - 1)
    md = extract_markdown(
        "<html></html>", extractor=lambda _h: tiny_primary, fallback=lambda _h: "short"
    )
    assert md == tiny_primary


def test_extract_markdown_threshold_boundary_just_under_triggers_fallback() -> None:
    """Primary at exactly _MIN_PRIMARY_CHARS - 1 chars is below threshold -> fallback
    considered (and wins here since it is longer)."""
    just_under = "a" * (_MIN_PRIMARY_CHARS - 1)
    fallback_text = "b" * (_MIN_PRIMARY_CHARS + 50)
    md = extract_markdown(
        "<html></html>", extractor=lambda _h: just_under, fallback=lambda _h: fallback_text
    )
    assert md == fallback_text


def test_extract_markdown_threshold_boundary_at_threshold_skips_fallback() -> None:
    """Primary at exactly _MIN_PRIMARY_CHARS chars meets the threshold -> fallback is
    never invoked, even though it would have produced more text."""

    def _spy_fallback(_html: str) -> str:
        raise AssertionError("fallback must not be called when primary meets the threshold")

    at_threshold = "a" * _MIN_PRIMARY_CHARS
    md = extract_markdown(
        "<html></html>", extractor=lambda _h: at_threshold, fallback=_spy_fallback
    )
    assert md == at_threshold


def test_extract_markdown_both_empty_returns_empty_string() -> None:
    """Primary and fallback both yield nothing -> '' (never None), so the conductor
    can mark the fetch as empty rather than crashing on a None."""
    md = extract_markdown("<html></html>", extractor=lambda _h: "", fallback=lambda _h: "")
    assert md == ""


def test_extract_markdown_default_fallback_is_readability_when_primary_is_weak() -> None:
    """With no injected extractor or fallback, the real defaults are
    `_extract_markdown_default` (trafilatura) and `_readability_fallback` -- when
    the default primary is too weak on layouts that defeat trafilatura, readability
    should rescue the main-content block, end to end. (The
    fallback only default-fires on the DEFAULT primary path, so this test must not
    inject a custom `extractor` -- an injected extractor is used as-is.)"""
    html = (
        "<html><body><nav>Home | About</nav>"
        "<article><h1>Big Title</h1><p>"
        + ("This is the main content paragraph with real readable text. " * 5)
        + "</p></article><footer>Copyright 2026</footer></body></html>"
    )
    md = extract_markdown(html)
    assert "main content paragraph" in md


def test_extract_markdown_injected_extractor_short_result_used_verbatim() -> None:
    """An injected `extractor` is the caller taking control of
    extraction -- a short result from it is intentional, not a failure, so the
    default readability fallback must NOT second-guess it. No `fallback` is
    injected, so the spy proves it is never called."""

    def _spy_fallback(_html: str) -> str:
        raise AssertionError("fallback must not run for an injected extractor with no injected fallback")

    short = "short custom result"  # well under _MIN_PRIMARY_CHARS
    md = extract_markdown("<p>ignored</p>", extractor=lambda _h: short)
    assert md == short


def test_extract_markdown_injected_extractor_and_fallback_still_runs_fallback() -> None:
    """Injecting BOTH a short `extractor` and a `fallback`
    forces the fallback to run anyway -- the escape hatch that keeps the fallback
    path itself testable stays open."""
    md = extract_markdown(
        "<html></html>",
        extractor=lambda _h: "short",
        fallback=lambda _h: "the injected fallback ran and won",
    )
    assert md == "the injected fallback ran and won"


def test_readability_fallback_extracts_main_content_from_small_html_doc() -> None:
    """Direct test of the real readability path (Document(html).summary() -> text),
    no network: a small HTML doc with nav/footer boilerplate plus a clear
    main-content article -- the extracted text keeps the article and drops tags."""
    html = (
        "<html><body>"
        "<nav>Home | About | Contact</nav>"
        "<article><h1>Article Title</h1>"
        "<p>The quick brown fox jumps over the lazy dog many times in this "
        "readable paragraph of main content that readability should surface.</p>"
        "</article>"
        "<footer>Copyright 2026 Example Corp</footer>"
        "</body></html>"
    )
    text = _readability_fallback(html)
    assert "quick brown fox" in text
    assert "<p>" not in text
    assert "<article>" not in text


def test_readability_fallback_returns_empty_string_for_unparseable_html() -> None:
    """Garbage input must not raise -- readability's parser failures normalize to ''
    so the conductor can record an empty result instead of crashing."""
    assert _readability_fallback("") == ""


def test_extract_pdf_uses_the_injected_extractor() -> None:
    """PDF extraction delegates to an injectable extractor (real one is PyMuPDF/fitz)."""
    text = extract_pdf(b"%PDF fake", extractor=lambda _b: "paper text")
    assert text == "paper text"


def _make_in_memory_pdf(text: str) -> bytes:
    """Build a tiny single-page PDF in memory via fitz, for self-contained round-trip
    tests -- no fixture file, no network. Mirrors the brief's exact recipe."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_pdf_default_engine_extracts_real_digital_pdf_text() -> None:
    """The default (uninjected) extractor is the real fitz engine: text inserted into
    an in-memory PDF round-trips back out through extract_pdf."""
    pdf_bytes = _make_in_memory_pdf("Hello Spyglass")
    assert "Hello Spyglass" in extract_pdf(pdf_bytes)


def test_extract_pdf_default_engine_returns_empty_string_for_corrupt_bytes() -> None:
    """Unreadable/corrupt PDF bytes must not raise -- a fetch failure is data, so the
    conductor can record an empty result instead of crashing."""
    assert extract_pdf(b"not a pdf") == ""


def test_extract_pdf_corrupt_bytes_logs_a_warning_instead_of_silently_swallowing(
    caplog,
) -> None:
    """A corrupt PDF must not vanish into a bare "" with no
    trace -- that makes a real parse failure indistinguishable from a genuinely empty
    page. The fitz except-block must log at WARNING (via logger.exception, which sets
    exc_info) while still returning "" -- behaviour unchanged, only the error is now
    diagnosable."""
    with caplog.at_level(logging.WARNING, logger="spyglass_service.extractors.pdf"):
        result = extract_pdf(b"not a pdf")

    assert result == ""
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "PDF parse failed" in record.message
    assert record.exc_info is not None
