"""Parse the vault feed-list note into subscription URLs."""

import re

# Matches http(s) URLs while stopping before markdown/punctuation terminators.
_URL_PATTERN = re.compile(r"https?://[^\s)\]>\"',]+")


def parse_feed_list(text: str) -> list[str]:
    """Extract unique feed URLs from a human-edited markdown note, in order.

    The note is edited on desktop and mobile, so URLs may appear as bullets,
    markdown links, or bare lines. Trailing punctuation is stripped.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _URL_PATTERN.findall(text):
        url = raw.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
