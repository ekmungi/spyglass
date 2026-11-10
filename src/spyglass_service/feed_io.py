"""OPML and markdown read/write helpers for Spyglass feed import/export.

Uses defusedxml for OPML parsing (safe against XXE and billion-laughs attacks) and
stdlib xml.etree.ElementTree for building output (write path carries no parse risk).
lxml is not required.

Public API
----------
parse_opml(text)        -> list[str]   Extract xmlUrl values from OPML text.
build_opml(feeds)       -> str         Emit OPML 2.0 from a list of Feed rows.
build_markdown(feeds)   -> str         Emit a markdown bullet list parseable by parse_feed_list.
"""

import xml.etree.ElementTree as ET
from xml.etree.ElementTree import ParseError

import defusedxml
import defusedxml.ElementTree as defused_ET

from spyglass_service.models import Feed


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class OPMLParseError(ValueError):
    """Raised by parse_opml when the input is not valid XML.

    Wraps xml.etree.ElementTree.ParseError so callers receive a domain-level
    error they can map to a 422 HTTP response without coupling to stdlib internals.
    """


# ---------------------------------------------------------------------------
# OPML helpers
# ---------------------------------------------------------------------------


def parse_opml(text: str) -> list[str]:
    """Extract every xmlUrl attribute from an OPML document, recursing into folders.

    Folder outlines (those without an xmlUrl attribute) are skipped; only leaf
    outlines representing real feeds are collected. The order follows a depth-first
    traversal of the <body> element.

    Args:
        text: Raw OPML XML as a string.

    Returns:
        Ordered list of feed URLs (xmlUrl values); may be empty.

    Raises:
        OPMLParseError: When the input is not parseable XML.
    """
    try:
        root = defused_ET.fromstring(text)
    except (ParseError, defusedxml.DefusedXmlException) as exc:
        raise OPMLParseError(f"Cannot parse OPML: {exc}") from exc

    urls: list[str] = []
    body = root.find("body")
    if body is None:
        return urls

    _collect_xml_urls(body, urls)
    return urls


def _collect_xml_urls(element: ET.Element, out: list[str]) -> None:
    """Recursively collect xmlUrl values from <outline> elements.

    Args:
        element: An XML element whose children may be <outline> nodes.
        out: Accumulator list; xmlUrl values are appended in depth-first order.
    """
    for outline in element.findall("outline"):
        xml_url = outline.get("xmlUrl")
        if xml_url:
            out.append(xml_url)
        # Always recurse — a folder outline may contain feed outlines.
        _collect_xml_urls(outline, out)


def build_opml(feeds: list[Feed]) -> str:
    """Emit a well-formed OPML 2.0 document from a list of Feed rows.

    Each feed becomes one flat <outline type="rss" text=NAME title=NAME xmlUrl=URL/>.
    The output is round-trip-safe: parse_opml(build_opml(feeds)) returns the same
    URL set.

    Args:
        feeds: Feed rows to serialise (id may be None for unsaved stubs).

    Returns:
        OPML 2.0 XML string, UTF-8 encoded, with XML declaration.
    """
    opml_el = ET.Element("opml", {"version": "2.0"})

    head_el = ET.SubElement(opml_el, "head")
    title_el = ET.SubElement(head_el, "title")
    title_el.text = "Spyglass feeds"

    body_el = ET.SubElement(opml_el, "body")
    for feed in feeds:
        ET.SubElement(
            body_el,
            "outline",
            {
                "type": "rss",
                "text": feed.name,
                "title": feed.name,
                "xmlUrl": feed.feed_url,
            },
        )

    ET.indent(opml_el, space="  ")
    raw = ET.tostring(opml_el, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="utf-8"?>\n{raw}\n'


def build_markdown(feeds: list[Feed]) -> str:
    """Emit a markdown bullet list of feed subscriptions, one per line.

    Each line is formatted as `- [name](url)` which is both human-readable and
    parseable by parse_feed_list (the regex extracts https:// URLs from any
    bullet/link syntax). The output is round-trip-safe.

    Args:
        feeds: Feed rows to serialise.

    Returns:
        Markdown string where each feed is a bullet link on its own line.
        Returns an empty string when feeds is empty.
    """
    if not feeds:
        return ""
    lines = [f"- [{feed.name}]({feed.feed_url})" for feed in feeds]
    return "\n".join(lines) + "\n"
