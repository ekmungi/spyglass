"""Small text conversions used by the reader builders.

`plain_text` derives the plain text stored for search and the assistant from sanitised HTML,
`markdown_to_html` (from `reader.markdown`, re-exported here) turns the markdown a fetch rung
may return into HTML (the sanitiser still runs afterwards), and `plain_abstract` cleans a feed
snippet into plain paragraphs.
"""

import re

from bs4 import BeautifulSoup

from spyglass_service.radar.reader.markdown import markdown_to_html  # noqa: F401 -- re-exported

_BLOCKS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre", "figcaption",
           "div", "section", "article", "table", "ul", "ol", "details", "summary", "figure", "hr"]
_ANNOUNCE = re.compile(r"^\s*arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*", re.IGNORECASE)


def plain_text(html: str) -> str:
    """Readable plain text of sanitised HTML: blocks become paragraphs, equations their TeX."""
    soup = BeautifulSoup(html or "", "html.parser")
    for math in soup.find_all("math"):
        math.replace_with(str(math.get("alttext", "")) or math.get_text(" ", strip=True))
    for cell in soup.find_all(["td", "th"]):
        cell.append(" | ")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(_BLOCKS):
        block.insert_before("\n\n")
        block.insert_after("\n\n")
    text = soup.get_text("")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def plain_abstract(summary: str | None) -> str:
    """A feed snippet as plain paragraphs, without markup or the arXiv announcement prefix."""
    if not summary:
        return ""
    soup = BeautifulSoup(summary, "html.parser")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if p) if paragraphs else soup.get_text(" ", strip=True)
    return _ANNOUNCE.sub("", text).strip()
