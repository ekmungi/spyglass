"""HTML-parsing helpers for feed_discovery.py (extracted to keep that module under 200 lines).

Parses <link rel=alternate> tags and in-page section/category links using
BeautifulSoup with the stdlib html.parser backend (no lxml, no XXE surface).
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# MIME types that indicate an RSS or Atom feed in a <link rel=alternate> tag.
_FEED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/rss+xml",
        "application/atom+xml",
        "application/feed+json",
        "application/json",  # JSON Feed sometimes uses this
    }
)

# Maximum number of in-page links crawled in deep mode.
MAX_CRAWL_LINKS = 25


def parse_declared_feeds(html: str, base_url: str) -> list[str]:
    """Extract absolute feed URLs from <link rel=alternate type=rss/atom> tags.

    Resolves relative hrefs against base_url. Ignores tags whose type is not a
    recognised feed MIME type. Uses BeautifulSoup with the stdlib html.parser
    backend — no lxml, no XXE risk.

    Args:
        html: Raw HTML text of the page.
        base_url: The URL the page was fetched from (used to resolve relative hrefs).

    Returns:
        List of absolute feed URLs found in <link> tags (may be empty).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[str] = []
    for tag in soup.find_all("link", rel=True):
        rel = tag.get("rel", [])
        # rel can be a list (bs4 normalisation) or a string.
        rel_values = rel if isinstance(rel, list) else [rel]
        if "alternate" not in rel_values:
            continue
        mime = (tag.get("type") or "").strip().lower()
        if mime not in _FEED_MIME_TYPES:
            continue
        href = (tag.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        results.append(absolute)
    return results


def parse_section_links(html: str, base_url: str) -> list[str]:
    """Extract same-origin in-page <a href> links suitable for one-level crawling.

    Limits to MAX_CRAWL_LINKS total. Skips external links, anchors (#), and
    obviously non-HTML targets (images, scripts, stylesheets, feeds).

    Args:
        html: Raw HTML text of the page.
        base_url: The URL the page was fetched from (used to resolve relative hrefs
            and filter to same origin).

    Returns:
        List of absolute same-origin URLs (at most MAX_CRAWL_LINKS).
    """
    base_origin = _origin(base_url)
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    results: list[str] = []

    for tag in soup.find_all("a", href=True):
        if len(results) >= MAX_CRAWL_LINKS:
            break
        href = (tag.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        if _origin(absolute) != base_origin:
            continue  # skip external links
        # Skip obvious non-HTML resources.
        path_lower = urlparse(absolute).path.lower()
        if any(path_lower.endswith(ext) for ext in (".xml", ".rss", ".atom", ".json", ".png",
                                                      ".jpg", ".gif", ".css", ".js", ".pdf")):
            continue
        # Remove fragments and normalise.
        clean = absolute.split("#")[0].rstrip("/") or absolute
        if clean in seen:
            continue
        seen.add(clean)
        results.append(clean)

    return results


def _origin(url: str) -> str:
    """Return scheme+host of url (e.g. 'https://example.com').

    Args:
        url: Any URL string.

    Returns:
        Lowercased scheme+netloc, or empty string on parse failure.
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}".lower()
    except Exception:
        return ""
