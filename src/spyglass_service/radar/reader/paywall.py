"""Recognise a paywalled preview: the page is real, but the site shows only the start of the article.

A preview is kept (the reader still shows what the site gave away) but marked, so the reader is
told the text is partial and the assistant does not present it as the whole article.
"""

import re
from urllib.parse import urlsplit

# The notice shown with a partial document.
PARTIAL_NOTICE = "Only a preview is available; the site limits this article to subscribers."
# Sites that limit most articles to subscribers. STAT is separate: only its paid "STAT+" pieces count.
PAYWALLED_HOSTS = (
    "wsj.com", "ft.com", "nytimes.com", "bloomberg.com", "economist.com", "theinformation.com",
    "barrons.com",
)
_STAT_HOST = "statnews.com"
_STAT_MARKER = re.compile(r"STAT\+|/plus/", re.IGNORECASE)
# On a paywalled site, a text this long is the whole article (previews are a few paragraphs).
_FULL_ARTICLE_WORDS = 700
# Elsewhere, a preview phrase on a text shorter than this marks a preview.
_PREVIEW_MAX_WORDS = 200
_PREVIEW_PHRASES = (
    "subscribe to continue", "already a subscriber", "sign in to read", "subscribe to read",
    "to continue reading", "for subscribers only", "this article is for subscribers",
    "log in to read", "create a free account to continue", "subscribers can read",
)


def _on_host(url: str, domain: str) -> bool:
    """True when `url` is on `domain` or one of its subdomains."""
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def looks_partial(text: str, item_url: str, final_url: str) -> bool:
    """True when `text` is probably only the preview of a subscriber-only article.

    A well-known paywalled site with fewer than 700 words, a STAT+ piece with fewer than 700 words,
    or any site whose text is under 200 words and contains a phrase such as "Subscribe to continue".
    """
    words = len(text.split())
    urls = (item_url, final_url)
    if words < _FULL_ARTICLE_WORDS:
        if any(_on_host(u, d) for u in urls for d in PAYWALLED_HOSTS):
            return True
        if any(_on_host(u, _STAT_HOST) for u in urls) and (
                _STAT_MARKER.search(text) or any(_STAT_MARKER.search(u) for u in urls)):
            return True
    lowered = text.lower()
    return words < _PREVIEW_MAX_WORDS and any(phrase in lowered for phrase in _PREVIEW_PHRASES)
