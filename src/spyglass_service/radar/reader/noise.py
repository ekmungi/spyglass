"""Remove page furniture that extraction leaves inside article text: stock tickers and hash strings.

A news page often carries a live quote widget ("NVDA 2.87%increase; up pointing triangle") or a
tracking token in the middle of the story. Neither is prose, so both are dropped, together with
any block that is left empty.
"""

import re

from bs4 import BeautifulSoup, NavigableString

# The accessibility text of a quote widget: symbol, change, direction ("up pointing triangle").
_TICKER = re.compile(
    r"\b[A-Z]{1,5}\s+[+\-−]?\d+(?:\.\d+)?%\s*(?:increase|decrease)\W{0,3}(?:up|down)\s+pointing\s+"
    r"(?:small\s+)?triangle\b"
)
# A long run of hexadecimal digits (a content hash) anywhere in text.
_HEX_HASH = re.compile(r"\b[0-9a-fA-F]{32,}\b")
# A whole text block that is one long opaque token with both letters and digits.
_OPAQUE_BLOCK = re.compile(r"^(?=[^\s]*\d)(?=[^\s]*[A-Za-z])[A-Za-z0-9+/_=\-]{24,}$")
_KEEP_VERBATIM = ("pre", "code", "script", "style", "textarea")
_BLOCKS = ("p", "li", "div", "span", "td", "th", "figcaption", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6")


def strip_page_noise(html: str) -> str:
    """`html` without ticker fragments and bare hash-like tokens; empty blocks they leave are removed."""
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    touched = False
    for node in list(soup.find_all(string=True)):
        if type(node) is not NavigableString or node.find_parent(_KEEP_VERBATIM):
            continue
        text = str(node)
        cleaned = _HEX_HASH.sub("", _TICKER.sub("", text))
        if _OPAQUE_BLOCK.match(cleaned.strip()) and node.parent.name in _BLOCKS:
            cleaned = ""
        if cleaned != text:
            touched = True
            node.replace_with(NavigableString(re.sub(r"[ \t]{2,}", " ", cleaned)))
    if not touched:
        return html
    for tag in soup.find_all(_BLOCKS):
        if not tag.get_text(strip=True) and not tag.find(["img", "table", "video", "iframe", "svg"]):
            tag.decompose()
    return str(soup)
