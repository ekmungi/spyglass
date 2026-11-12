"""Turn a web page into a clean reading document: structure, images, tables and links kept.

Two extractors run on the same page: trafilatura (precise, drops most boilerplate) and
readability-lxml (more forgiving of odd layouts). A small quality rule picks the better result,
which is then sanitised by `clean_html`. Title, byline, site name and lead image come from the
page's metadata (Open Graph tags and the extractors' own metadata) when the body lacks them.
"""

import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from spyglass_service.radar.reader.inline import protect_inline, restore_inline, wrap_block_code
from spyglass_service.radar.reader.sanitize import clean_html, promote_lazy_images

logger = logging.getLogger(__name__)

# A candidate with fewer words than this is only used when nothing better exists: it is
# probably a cookie notice, an error page or a login wall rather than an article.
MIN_WORDS = 40
# More than this share of the words inside links means the extractor kept a menu or link list.
MAX_LINK_RATIO = 0.5
# Trafilatura output is cleaner, so it wins when it keeps at least this share of the longer text.
TRAFILATURA_PREFERENCE = 0.6
# Each image or table counts as this many words when comparing two extractions.
RICH_BLOCK_WORDS = 25
_HEADINGS = ("h1", "h2", "h3")


def count_words(html: str) -> int:
    """Number of whitespace-separated words in the visible text of `html`."""
    return len(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())


def _link_ratio(soup: BeautifulSoup) -> float:
    """Share of words that sit inside links (1.0 for a page that is only links)."""
    total = len(soup.get_text(" ", strip=True).split())
    if total == 0:
        return 1.0
    linked = sum(len(a.get_text(" ", strip=True).split()) for a in soup.find_all("a"))
    return min(linked / total, 1.0)


def _prepare_page(raw_html: str) -> str:
    """The page with lazy-load image attributes promoted, so the extractors see real image URLs."""
    soup = BeautifulSoup(raw_html, "html.parser")
    promote_lazy_images(soup)
    return str(soup)


def _trafilatura_html(raw_html: str, url: str) -> str:
    """Main-content HTML from trafilatura with images, tables, links and formatting kept."""
    import trafilatura

    try:
        extracted = trafilatura.extract(
            protect_inline(raw_html), url=url, output_format="html", include_images=True, include_tables=True,
            include_links=True, include_formatting=True, include_comments=False,
        ) or ""
    except Exception:  # noqa: BLE001 -- extractor bugs must not break the reader
        logger.exception("trafilatura failed for %s", url)
        return ""
    # Trafilatura keeps its own <graphic> element for images in HTML output.
    return restore_inline(re.sub(r"<graphic", "<img", extracted))


def _readability_html(raw_html: str, url: str) -> tuple[str, str]:
    """Main-content HTML and a short title from readability-lxml; ("", "") on failure."""
    from readability import Document

    try:
        doc = Document(raw_html, url=url)
        return doc.summary(html_partial=True), doc.short_title() or ""
    except Exception:  # noqa: BLE001 -- readability raises on pages without a body
        logger.exception("readability failed for %s", url)
        return "", ""


def _pick(traf: str, read: str) -> str:
    """Choose between the two extractions using word count and link density."""
    scored = []
    for name, html in (("trafilatura", traf), ("readability", read)):
        if not html.strip():
            continue
        soup = BeautifulSoup(html, "html.parser")
        words = len(soup.get_text(" ", strip=True).split())
        # Images and tables are content too: an extractor that dropped them loses to one that kept them.
        richness = words + RICH_BLOCK_WORDS * (len(soup.find_all("img")) + len(soup.find_all("table")))
        scored.append((name, html, words, _link_ratio(soup), richness))
    if not scored:
        return ""
    eligible = [s for s in scored if s[2] >= MIN_WORDS and s[3] <= MAX_LINK_RATIO]
    pool = eligible or scored
    best = max(pool, key=lambda s: s[4])
    traf_entry = next((s for s in pool if s[0] == "trafilatura"), None)
    if traf_entry and traf_entry[4] >= TRAFILATURA_PREFERENCE * best[4]:
        return traf_entry[1]
    return best[1]


def _meta(soup: BeautifulSoup, *names: str) -> str:
    """The first non-empty content of a <meta> with one of these property/name values."""
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and str(tag.get("content", "")).strip():
            return str(tag["content"]).strip()
    return ""


def _metadata(raw_html: str, url: str, readability_title: str) -> dict[str, str]:
    """Title, byline, site and lead image for the page, best source first."""
    import trafilatura

    soup = BeautifulSoup(raw_html, "html.parser")
    try:
        found = trafilatura.extract_metadata(raw_html, default_url=url)
    except Exception:  # noqa: BLE001 -- metadata is optional; fall back to the tags below
        logger.exception("trafilatura metadata failed for %s", url)
        found = None
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    host = urlsplit(url).netloc.removeprefix("www.")
    image = _meta(soup, "og:image", "twitter:image") or (found.image if found and found.image else "")
    image = urljoin(url, image) if image else ""
    return {
        "title": _meta(soup, "og:title") or (found.title if found and found.title else "")
        or readability_title or page_title,
        "byline": (found.author if found and found.author else "")
        or _meta(soup, "author", "article:author"),
        "site": _meta(soup, "og:site_name") or (found.sitename if found and found.sitename else "")
        or host,
        "lead_image": image if urlsplit(image).scheme in ("http", "https") else "",
    }


def _strip_site_suffix(title: str, site: str) -> str:
    """Remove a trailing " | Site Name" (or "- Site Name") that the page appended to its title."""
    for separator in (" | ", " - ", " – ", " — ", " :: ", " · "):
        suffix = separator + site
        if site and title.lower().endswith(suffix.lower()) and len(title) > len(suffix) + 5:
            return title[: -len(suffix)].rstrip()
    return title


def _normalise(text: str) -> str:
    """Lower-case alphanumerics only, for comparing a heading with the title."""
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def drop_duplicate_title(html: str, title: str) -> str:
    """Remove a leading heading that repeats the page title (the reader shows the title itself)."""
    if not html or not title:
        return html
    soup = BeautifulSoup(html, "html.parser")
    target = _normalise(title)
    for heading in soup.find_all(_HEADINGS, limit=2):
        text = _normalise(heading.get_text(" ", strip=True))
        if text and (text == target or (len(text) > 12 and (text in target or target in text))):
            heading.decompose()
            break
    return str(soup)


def extract_article(raw_html: str, url: str) -> dict:
    """Extract the readable article of a page.

    Returns {html, title, byline, site, lead_image, word_count}: `html` is sanitised and safe to
    inject; every other field is plain text ("" when unknown). `html` is "" and `word_count` 0
    when the page holds no readable text.
    """
    if not raw_html or not raw_html.strip():
        return {"html": "", "title": "", "byline": "", "site": "", "lead_image": "", "word_count": 0}
    page = _prepare_page(raw_html)
    traf = _trafilatura_html(page, url)
    read, read_title = _readability_html(page, url)
    meta = _metadata(raw_html, url, read_title)
    meta["title"] = _strip_site_suffix(meta["title"], meta["site"])
    chosen = wrap_block_code(drop_duplicate_title(_pick(traf, read), meta["title"]))
    cleaned = clean_html(chosen, url)
    return {**meta, "html": cleaned, "word_count": count_words(cleaned) if cleaned else 0}
