"""Turn a fetched web page (HTML or a fetch service's markdown) into the fields of an article document.

This is the generic article path of the reader build: it extracts or converts the body, removes
page furniture, rejects pages that are not articles (block pages, trackers, stubs), and marks a
paywalled preview as partial instead of presenting it as the whole article.
"""

from datetime import datetime

from spyglass_service.radar.reader.article import count_words, extract_article
from spyglass_service.radar.reader.blocked import (
    BLOCKED_REASON, STUB_REASON, is_stub_page, looks_blocked,
)
from spyglass_service.radar.reader.http import BuildFailure, Page
from spyglass_service.radar.reader.markdown import markdown_to_html, parse_fetch_markdown
from spyglass_service.radar.reader.noise import strip_page_noise
from spyglass_service.radar.reader.paywall import PARTIAL_NOTICE, looks_partial
from spyglass_service.radar.reader.sanitize import clean_html
from spyglass_service.radar.reader.text import plain_text

# Fewer words than this means the page was a stub, a paywall or a login wall, not an article.
MIN_ARTICLE_WORDS = 25
# A fetch service that reports the target site's own error (403, 413) is a block page below this size.
_ERROR_PAGE_WORDS = 120


def _published_label(value: str) -> str:
    """"Published 9 Nov 2026" from an ISO timestamp, "" when the value cannot be read."""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return ""
    return f"Published {moment.day} {moment:%b %Y}"


def _service_title(title: str, fallback: str) -> str:
    """The service's page title, or `fallback` when it is empty or just an address."""
    cleaned = title.strip()
    return fallback if not cleaned or cleaned.lower().startswith(("http://", "https://")) else cleaned


def _from_service_markdown(item_url: str, item_title: str, page: Page) -> tuple[str, dict, str, int | None]:
    """HTML, metadata, final address and target error of a page the fetch service rendered as markdown."""
    parsed = parse_fetch_markdown(page.text)
    html = clean_html(markdown_to_html(parsed.body), parsed.source_url or item_url)
    meta = {"title": _service_title(parsed.title, item_title), "byline": _published_label(parsed.published),
            "site": "", "lead_image": ""}
    return html, meta, parsed.final_url or page.url, parsed.target_error


def build_article_fields(item_url: str, item_title: str, page: Page) -> dict:
    """The reader fields of an article built from a fetched page.

    Raises `BuildFailure` with a reader-facing reason when the page is a block page, a tracker or
    stub, or has no readable text. A likely paywalled preview is returned with status "partial"
    and `PARTIAL_NOTICE` as its notice.
    """
    target_error: int | None = None
    if page.is_markdown:
        html, meta, final_url, target_error = _from_service_markdown(item_url, item_title, page)
    else:
        article = extract_article(page.text, page.url)
        html, final_url = article["html"], page.url
        meta = {k: article[k] for k in ("title", "byline", "site", "lead_image")}
    html = strip_page_noise(html)
    text = plain_text(html)
    words = count_words(html) if html else 0
    if looks_blocked(text, meta["title"]) or (target_error and words < _ERROR_PAGE_WORDS):
        raise BuildFailure(BLOCKED_REASON)
    if words < MIN_ARTICLE_WORDS or is_stub_page(text, item_url, final_url):
        raise BuildFailure(STUB_REASON)
    fields = {
        **meta, "kind": "article", "html": html, "word_count": words, "source_url": item_url,
        "alt_url": None, "title": meta["title"] or item_title,
    }
    if looks_partial(text, item_url, final_url):
        fields.update(status="partial", error=PARTIAL_NOTICE)
    return fields
