"""The quick title fetch behind a capture: one small, guarded request for a page's own title.

Every hop is checked with `netguard.is_public_url` before it is requested (redirects are
followed by hand), at most MAX_TITLE_BYTES of the page are read, and the bytes are decoded with
the character set the response or the page itself declares, falling back to UTF-8 and then
Windows-1252. The replacement character is never returned.
"""

import html
import logging
import re
from collections.abc import Callable
from urllib.parse import urljoin

import httpx

from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

# Seconds the title fetch may take before the capture proceeds without a title.
TITLE_TIMEOUT = 8.0
# How many redirects are followed; each hop is checked before it is requested.
MAX_TITLE_REDIRECTS = 5
# A page's title is near its top; reading more than this would only cost memory and time.
MAX_TITLE_BYTES = 512 * 1024
# How far into the page a <meta charset> declaration is looked for.
_META_SCAN_BYTES = 8192
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_OG_TITLE = re.compile(
    r"""<meta[^>]+property\s*=\s*["']og:title["'][^>]*content\s*=\s*["']([^"']*)["']""", re.I)
_REPLACEMENT = "�"

ClientFactory = Callable[[], httpx.Client]


def _default_client() -> httpx.Client:
    """The guarded page-fetch client with a short timeout and no automatic redirects.

    Read-only, no cookies or credential headers, the generic agent; each hop is also checked here.
    """
    return netguard.page_client(timeout=TITLE_TIMEOUT, follow_redirects=False)


def _read_capped(response: httpx.Response, limit: int) -> bytes:
    """At most `limit` bytes of the response body, stopping the download there."""
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= limit:
            break
    return b"".join(chunks)[:limit]


def _try_decode(body: bytes, encoding: str | None) -> str | None:
    """`body` decoded strictly with `encoding`, or None when it is unknown or does not fit."""
    if not encoding:
        return None
    try:
        return body.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return None


def decode_page(body: bytes, declared: str | None) -> str:
    """Decode a page: the response's charset, the page's <meta charset>, UTF-8, Windows-1252.

    Each candidate must decode the bytes without error; the last resort replaces what it cannot
    read, and replacement characters are removed from the result.
    """
    match = _META_CHARSET.search(body[:_META_SCAN_BYTES])
    meta = match.group(1).decode("ascii", "ignore") if match else None
    for encoding in (declared, meta, "utf-8", "cp1252"):
        text = _try_decode(body, encoding)
        if text is not None:
            return text.replace(_REPLACEMENT, "")
    return body.decode("cp1252", errors="replace").replace(_REPLACEMENT, "")


def extract_title(page: str) -> str | None:
    """The page's title: its og:title, else its <title>, unescaped and on one line."""
    for pattern in (_OG_TITLE, _TITLE_TAG):
        match = pattern.search(page)
        if match:
            title = " ".join(html.unescape(match.group(1)).split()).replace(_REPLACEMENT, "")
            if title:
                return title[:500]
    return None


def fetch_title(url: str, *, client_factory: ClientFactory | None = None,
                resolver: netguard.Resolver | None = None) -> str | None:
    """The page's own title, or None when it cannot be fetched safely or has none.

    Args:
        url: A public http(s) address.
        client_factory: Builds the HTTP client (tests pass one with a fake transport).
        resolver: Host-name resolver used by the address check (tests pass a stub).
    """
    try:
        with (client_factory or _default_client)() as client:
            current = url
            for _ in range(MAX_TITLE_REDIRECTS + 1):
                if not netguard.is_public_url(current, resolver=resolver):
                    return None
                with client.stream("GET", current) as response:
                    location = response.headers.get("location")
                    if response.is_redirect and location:
                        current = urljoin(current, location)
                        continue
                    content_type = response.headers.get("content-type", "")
                    if response.status_code != 200 or "html" not in content_type.lower():
                        return None
                    body = _read_capped(response, MAX_TITLE_BYTES)
                    declared = response.charset_encoding
                return extract_title(decode_page(body, declared))
    except httpx.HTTPError as exc:
        logger.info("title fetch for %s failed: %s", url, exc)
    return None
