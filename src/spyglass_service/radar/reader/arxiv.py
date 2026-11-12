"""arXiv papers: the HTML edition when one exists, otherwise a notice and the PDF.

arXiv renders many papers to HTML (LaTeXML) at `arxiv.org/html/<id>`, with MathML equations,
real tables and figures. A paper without that edition answers 404. For those, the reader shows
the abstract and the built-in PDF viewer.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from spyglass_service.radar.reader.article import count_words
from spyglass_service.radar.reader.http import Fetcher
from spyglass_service.radar.reader.pdf import pdf_result
from spyglass_service.radar.reader.sanitize import clean_html

logger = logging.getLogger(__name__)

_ID_PATTERN = (
    r"(?:\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?"
)
_ARXIV_URL = re.compile(
    rf"^https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|html)/({_ID_PATTERN})(?:\.pdf)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_MAX_AUTHORS = 12
# LaTeXML marks formatting with classes, which the sanitiser drops; these become real tags.
_FORMAT_CLASSES = {
    "ltx_font_bold": "strong", "ltx_font_italic": "em", "ltx_font_typewriter": "code",
    "ltx_font_smallcaps": "span", "ltx_font_oblique": "em",
}


def arxiv_id(url: str) -> str | None:
    """The arXiv identifier in an abs, pdf or html URL (with its version if present), else None."""
    match = _ARXIV_URL.match(url.strip())
    return match.group(1) if match else None


def pdf_url(aid: str) -> str:
    """The PDF address of an arXiv paper."""
    return f"https://arxiv.org/pdf/{aid}"


def html_url(aid: str) -> str:
    """The HTML-edition address of an arXiv paper."""
    return f"https://arxiv.org/html/{aid}"


def abs_url(aid: str) -> str:
    """The abstract-page address of an arXiv paper."""
    return f"https://arxiv.org/abs/{aid}"


def _authors(article: Tag) -> str:
    """Author names from LaTeXML's author block (the first line of each person entry)."""
    names: list[str] = []
    for person in article.select(".ltx_authors .ltx_personname"):
        first = next((s.strip() for s in person.stripped_strings), "")
        if first and first not in names:
            names.append(first)
    shown = names[:_MAX_AUTHORS]
    extra = len(names) - len(shown)
    return ", ".join(shown) + (f" and {extra} more" if extra > 0 else "")


def _rewrite_formatting(article: Tag) -> None:
    """Turn LaTeXML formatting classes into tags and drop list-marker duplicates."""
    for span in article.find_all("span"):
        for cls in span.get("class") or []:
            tag = _FORMAT_CLASSES.get(cls)
            if tag and tag != "span":
                span.name = tag
                break
    # Browsers number and bullet lists themselves; the generated tag text would double it.
    for tag in article.select(".ltx_tag_item"):
        tag.decompose()


def _html_edition(page_html: str, url: str, fallback_title: str) -> dict | None:
    """Reader fields from an arXiv HTML page, or None when it is not a LaTeXML paper."""
    soup = BeautifulSoup(page_html, "html.parser")
    article = soup.find("article", class_="ltx_document")
    if not isinstance(article, Tag):
        return None
    title_tag = article.find(class_="ltx_title_document")
    title = title_tag.get_text(" ", strip=True) if title_tag else fallback_title
    byline = _authors(article)
    for selector in (".ltx_title_document", ".ltx_authors", ".ltx_dates", ".ltx_pagination"):
        for node in article.select(selector):
            node.decompose()
    _rewrite_formatting(article)
    cleaned = clean_html(str(article), url)
    if count_words(cleaned) < 100:
        return None
    return {
        "kind": "paper", "html": cleaned, "title": title or fallback_title, "byline": byline,
        "site": "arXiv", "lead_image": "", "word_count": count_words(cleaned),
        "source_url": url, "alt_url": None,
    }


def _abstract_from_abs_page(page_html: str) -> tuple[str, str, str]:
    """(title, authors, abstract) from an arXiv abstract page; empty strings where missing."""
    soup = BeautifulSoup(page_html, "html.parser")

    def meta(name: str) -> list[str]:
        """All content values of a <meta name=...> tag."""
        return [str(t.get("content", "")).strip() for t in soup.find_all("meta", attrs={"name": name})]

    title = (meta("citation_title") or [""])[0]
    authors = ", ".join(meta("citation_author")[:_MAX_AUTHORS])
    block = soup.find("blockquote", class_="abstract")
    abstract = ""
    if block:
        abstract = re.sub(r"^\s*Abstract:\s*", "", block.get_text(" ", strip=True))
    return title, authors, abstract


def build_arxiv(aid: str, *, title: str, abstract: str, fetch: Fetcher) -> dict:
    """Build the reader fields for arXiv paper `aid`.

    `title` and `abstract` come from the stored item and are used when the arXiv pages cannot
    supply them. Returns a dict with kind "paper" (HTML edition) or "pdf" (no HTML edition).
    """
    page = fetch(html_url(aid))
    # A missing edition answers 404/410. Anything else that is not an HTML page (a network error,
    # or the fetch ladder falling through to a text-only rung) is uncertain: show the PDF view,
    # but say so, because the paper may well have an edition that can be loaded on a retry.
    uncertain = (not page.ok and page.status not in (404, 410)) or (page.ok and page.is_markdown)
    if page.ok and not page.is_pdf and not page.is_markdown:
        try:
            fields = _html_edition(page.text, page.url, title)
        except Exception:  # noqa: BLE001 -- a malformed edition falls back to the PDF view
            logger.exception("arXiv HTML edition of %s could not be parsed", aid)
            fields = None
        if fields is not None:
            return {**fields, "alt_url": pdf_url(aid)}
    byline = ""
    if not abstract.strip():
        abs_page = fetch(abs_url(aid))
        if abs_page.ok:
            found_title, byline, abstract = _abstract_from_abs_page(abs_page.text)
            title = title or found_title
    return pdf_result(
        pdf_url(aid), title, abstract,
        notice=(
            "arXiv's HTML edition could not be loaded just now, so this paper is shown as a PDF. "
            "Use Refresh to try again."
            if uncertain else "This paper has no HTML edition on arXiv, so it is shown as a PDF."
        ),
        source_url=abs_url(aid), byline=byline, site="arXiv",
    )
