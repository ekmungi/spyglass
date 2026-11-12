"""Tests for the arXiv builder: id detection, the HTML edition and the PDF-only fallback."""

import pytest

from spyglass_service.radar.reader.arxiv import (
    abs_url, arxiv_id, build_arxiv, html_url, pdf_url,
)
from spyglass_service.radar.reader.http import Page

_WORDS = "evidence retrieval differential reasoning model benchmark accuracy " * 30


def _edition(extra: str = "") -> str:
    """A minimal LaTeXML-style arXiv HTML edition with authors, abstract, math, table, figure."""
    return f"""<!DOCTYPE html><html><head><title>t</title></head><body>
    <header class="mob_header">site chrome</header><nav class="ltx_page_navbar">menu</nav>
    <div class="ltx_page_main"><article class="ltx_document">
    <h1 class="ltx_title ltx_title_document">A Paper About Evidence</h1>
    <div class="ltx_authors"><span class="ltx_creator"><span class="ltx_personname">Ada Lovelace
    </span><span class="ltx_author_notes">Dept of Maths</span></span>
    <span class="ltx_creator"><span class="ltx_personname">Alan Turing</span></span></div>
    <div class="ltx_abstract"><h6>Abstract</h6><p>{_WORDS}</p></div>
    <section class="ltx_section"><h2 class="ltx_title ltx_title_section">
    <span class="ltx_tag ltx_tag_section">1 </span>Intro</h2>
    <p>We use <span class="ltx_text ltx_font_bold">bold</span> claims and the equation
    <math display="inline" alttext="x^2"><semantics><msup><mi>x</mi><mn>2</mn></msup>
    <annotation encoding="application/x-tex">x^2</annotation></semantics></math> here. {_WORDS}</p>
    <ul class="ltx_itemize"><li><span class="ltx_tag ltx_tag_item">&bull;</span>first</li></ul>
    <figure class="ltx_figure"><img src="2401.00001v1/fig1.png" alt="Refer to caption" width="400">
    <figcaption>Figure 1</figcaption></figure>
    <figure class="ltx_table"><table class="ltx_tabular"><tr><td>a</td><td>b</td></tr></table></figure>
    {extra}</section></article></div>
    <footer class="ltx_page_footer">Report issue</footer><button>Report</button></body></html>"""


def _page(url: str, html: str, *, ok: bool = True, status: int | None = 200) -> Page:
    return Page(url=url, ok=ok, body=html.encode(), content_type="text/html", status=status,
                error=None if ok else f"HTTP {status}")


@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/abs/2401.12345", "2401.12345"),
    ("https://arxiv.org/abs/2401.12345v2", "2401.12345v2"),
    ("https://arxiv.org/pdf/2401.12345v1.pdf", "2401.12345v1"),
    ("https://arxiv.org/pdf/2401.12345", "2401.12345"),
    ("https://arxiv.org/html/2401.12345v3", "2401.12345v3"),
    ("http://www.arxiv.org/abs/2401.1234", "2401.1234"),
    ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
    ("https://export.arxiv.org/abs/2401.12345?context=cs", "2401.12345"),
])
def test_arxiv_id_detects_all_url_forms(url: str, expected: str) -> None:
    assert arxiv_id(url) == expected


@pytest.mark.parametrize("url", [
    "https://example.com/abs/2401.12345", "https://arxiv.org/list/cs.AI/recent",
    "https://arxiv.org/abs/", "https://notarxiv.org/abs/2401.12345", "",
])
def test_arxiv_id_rejects_other_urls(url: str) -> None:
    assert arxiv_id(url) is None


def test_url_helpers() -> None:
    assert pdf_url("2401.12345v1") == "https://arxiv.org/pdf/2401.12345v1"
    assert html_url("2401.12345") == "https://arxiv.org/html/2401.12345"
    assert abs_url("2401.12345") == "https://arxiv.org/abs/2401.12345"


def test_html_edition_becomes_a_paper_document() -> None:
    seen: list[str] = []

    def fetch(url: str, headers=None) -> Page:
        seen.append(url)
        return _page("https://arxiv.org/html/2401.00001v1", _edition())

    result = build_arxiv("2401.00001v1", title="fallback", abstract="", fetch=fetch)
    html = result["html"]
    assert result["kind"] == "paper"
    assert result["alt_url"] == "https://arxiv.org/pdf/2401.00001v1"
    assert result["title"] == "A Paper About Evidence"
    assert result["byline"] == "Ada Lovelace, Alan Turing"
    assert "<math" in html and "<annotation" in html and "<msup>" in html
    assert "<strong>bold</strong>" in html
    assert "<table" in html
    assert 'src="https://arxiv.org/html/2401.00001v1/fig1.png"' in html
    assert "site chrome" not in html and "Report issue" not in html and "menu" not in html
    assert "A Paper About Evidence" not in html  # the title is shown by the reader, not the body
    assert "first" in html and "&bull;" not in html and "•" not in html
    assert seen == ["https://arxiv.org/html/2401.00001v1"]


def test_many_authors_are_abbreviated() -> None:
    names = "".join(f'<span class="ltx_creator"><span class="ltx_personname">Person {i}</span></span>'
                    for i in range(20))
    page_html = _edition().replace('<div class="ltx_authors">', f'<div class="ltx_authors">{names}')
    result = build_arxiv("2401.00001", title="t", abstract="", fetch=lambda u, headers=None: _page(u, page_html))
    assert result["byline"].endswith("more")


def test_missing_html_edition_falls_back_to_pdf_with_abstract() -> None:
    def fetch(url: str, headers=None) -> Page:
        return _page(url, "not found", ok=False, status=404)

    result = build_arxiv("2401.00002", title="My Paper", abstract="We study things.\n\nIt works.", fetch=fetch)
    assert result["kind"] == "pdf"
    assert result["alt_url"] == "https://arxiv.org/pdf/2401.00002"
    assert result["source_url"] == "https://arxiv.org/abs/2401.00002"
    assert "no HTML edition" in result["html"]
    assert "<h2>Abstract</h2>" in result["html"] and "We study things." in result["html"]


def test_pdf_fallback_reads_the_abstract_page_when_the_item_has_none() -> None:
    abs_html = ('<html><head><meta name="citation_title" content="Real Title">'
                '<meta name="citation_author" content="Smith, A."></head><body>'
                '<blockquote class="abstract"><span>Abstract:</span> Plain abstract text here.'
                '</blockquote></body></html>')

    def fetch(url: str, headers=None) -> Page:
        if "/html/" in url:
            return _page(url, "nope", ok=False, status=404)
        return _page(url, abs_html)

    result = build_arxiv("2401.00003", title="", abstract="", fetch=fetch)
    assert result["kind"] == "pdf"
    assert "Plain abstract text here." in result["html"]
    assert result["title"] == "Real Title"
    assert result["byline"] == "Smith, A."


def test_a_page_that_is_not_latexml_falls_back_to_pdf() -> None:
    result = build_arxiv("2401.00004", title="T", abstract="Abs.",
                         fetch=lambda u, headers=None: _page(u, "<html><body><p>hello</p></body></html>"))
    assert result["kind"] == "pdf"


def test_unreachable_arxiv_shows_the_pdf_view_with_a_retry_notice() -> None:
    def fetch(url: str, headers=None) -> Page:
        if "/html/" in url:
            return Page(url=url, ok=False, status=None, error="request failed: ConnectError")
        return _page(url, "<html></html>")

    result = build_arxiv("2401.00005", title="T", abstract="Abstract text.", fetch=fetch)
    assert result["kind"] == "pdf" and "Use Refresh" in result["html"] and "Abstract text." in result["html"]


def test_text_only_fallback_page_is_not_mistaken_for_an_edition() -> None:
    def fetch(url: str, headers=None) -> Page:
        return Page(url=url, ok=True, body="Target URL returned error 404", is_markdown=True)

    result = build_arxiv("2401.00007", title="T", abstract="Abstract text.", fetch=fetch)
    assert result["kind"] == "pdf" and "Use Refresh" in result["html"]


def test_hostile_markup_in_an_edition_is_sanitised() -> None:
    result = build_arxiv("2401.00006", title="T", abstract="", fetch=lambda u, headers=None: _page(
        u, _edition('<p>x<script>alert(1)</script><img src=x onerror=alert(1)></p>')))
    assert "alert(1)" not in result["html"] and "onerror" not in result["html"]
