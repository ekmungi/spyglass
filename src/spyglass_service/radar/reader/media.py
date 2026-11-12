"""Point a reader document's images at the service's image proxy.

`proxied_html` rewrites every `src` and `srcset` of `img` and `source` elements in a sanitized
document to `/api/radar/img?u=<url-encoded address>`, so the reader's browser asks this service
for images instead of contacting the sites that host them (see `radar/media_proxy.py`).
Inline `data:` images are left alone: they load nothing. Only the image attributes change; the
rest of the document is kept byte for byte.
"""

import html
import re
from urllib.parse import quote, urlsplit

PROXY_PATH = "/api/radar/img?u="

_TAG = re.compile(r"<(?:img|source)\b[^>]*>", re.IGNORECASE)
# A src or srcset attribute (not data-src: it must follow whitespace), double or single quoted.
_ATTR = re.compile(r"(\s(src|srcset)\s*=\s*)(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
# srcset candidates are split before each absolute address, so a comma inside an address stays.
_CANDIDATE_SPLIT = re.compile(r",\s*(?=(?:https?:)?//|data:)", re.IGNORECASE)


def proxied_url(raw: str) -> str:
    """The proxy address for one image address; non-web addresses (data:) are returned as given."""
    url = html.unescape(raw).strip()
    if url.startswith("//"):
        url = "https:" + url
    if urlsplit(url).scheme.lower() not in ("http", "https"):
        return raw
    return PROXY_PATH + quote(url, safe="")


def _proxied_srcset(value: str) -> str:
    """Every candidate address in a srcset rewritten, descriptors (1x, 640w) kept."""
    candidates = []
    for candidate in _CANDIDATE_SPLIT.split(html.unescape(value)):
        parts = candidate.strip().split(None, 1)
        if parts:
            candidates.append(" ".join([proxied_url(parts[0]), *parts[1:]]))
    return ", ".join(candidates)


def _rewrite_tag(match: re.Match) -> str:
    """One img/source tag with its image attributes pointed at the proxy."""

    def attr(m: re.Match) -> str:
        value = m.group(3) if m.group(3) is not None else m.group(4)
        new = _proxied_srcset(value) if m.group(2).lower() == "srcset" else proxied_url(value)
        return f'{m.group(1)}"{html.escape(new, quote=True)}"'

    return _ATTR.sub(attr, match.group(0))


def proxied_html(doc_html: str, enabled: bool) -> str:
    """`doc_html` with image addresses sent through the proxy; unchanged when not `enabled`."""
    if not enabled or not doc_html:
        return doc_html
    return _TAG.sub(_rewrite_tag, doc_html)


def proxied_reader(reader: dict | None, enabled: bool) -> dict | None:
    """A copy of an item's reader block with its HTML images and lead image proxied."""
    if not enabled or not reader:
        return reader
    lead = reader.get("lead_image")
    return {**reader, "html": proxied_html(reader.get("html") or "", True),
            "lead_image": proxied_url(lead) if lead else lead}
