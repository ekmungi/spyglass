# src/spyglass_service/brief_render.py
"""Deterministic Daily Brief markdown assembly: link substitution + sections.

The LLM only writes the narrative with [#n] tokens; everything verifiable -- card links,
the References list, the 'Also noticed' tail -- is rendered here in plain Python so a
model mistake can never fabricate a link.
"""

import re
from dataclasses import dataclass, field

# Matches a narrative reference token like [#12] or [12]; the digits are the 1-based item number.
# The # is optional to support both canonical [#n] and bare [n] forms written by the LLM.
_REF_TOKEN = re.compile(r"\[#?(\d+)\]")


@dataclass(frozen=True)
class FeaturedEntry:
    """Everything the renderer needs for one featured item (no ORM objects)."""

    card_id: int
    title: str
    # Publication name (item.origin) falling back to the collector name (item.source).
    origin: str
    # ISO date string of the article's publication (or the card's creation as fallback).
    published: str
    # Effective relevance level shown in the reference line ("medium"/"high").
    level: str
    # Previously-briefed related cards as (title, card_id), at most two.
    related: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class Bullet:
    """One grouped bullet plus its inline related items."""

    # The bullet prose, still carrying [#n] tokens for card-link substitution.
    text: str
    # Nearest OTHER corpus cards to this bullet's articles as (title, card_id); empty
    # when nothing qualified. Rendered as an indented 'Related:' sub-line.
    related: list[tuple[str, int]] = field(default_factory=list)


def _normalize_dashes(text: str) -> str:
    """Replace em (U+2014) and en (U+2013) dashes with plain punctuation.

    The humanizer voice contract bans em/en dashes in brief prose, but the ban is
    prompt-only and the model doesn't reliably obey it. This is the deterministic backstop:
    applied ONLY to LLM-authored narrative prose (lead, section headings, bullet text) and
    ONLY before card-link substitution runs, so a real card title containing a legitimate
    dash (produced later by _card_link) is never touched.
    """
    return text.replace("—", " - ").replace("–", "-")


def _card_link(title: str, card_id: int) -> str:
    """One in-app card link: [<title>](card:<id>).

    Link text is sanitized: square brackets in real titles (common on arXiv) would
    close the link early and orphan the rest of the line, and newlines would break
    the list item -- escape/flatten both so any title renders as one intact link.
    """
    safe = title.replace("[", r"\[").replace("]", r"\]").replace("\n", " ")
    return f"[{safe}](card:{card_id})"


def replace_refs(narrative: str, entries: list[FeaturedEntry]) -> str:
    """Replace every in-range [#n] token with the item's card link.

    Out-of-range tokens (the model hallucinated a number) are left verbatim -- rendering
    them as text is honest; inventing a link would not be.

    Args:
        narrative: The LLM narrative containing [#n] tokens.
        entries: Featured entries in reference order (entry i is token [#i+1]).

    Returns:
        The narrative with tokens substituted by markdown card links.
    """
    def _sub(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= len(entries):
            entry = entries[n - 1]
            return _card_link(entry.title, entry.card_id)
        return match.group(0)

    return _REF_TOKEN.sub(_sub, narrative)


def render_brief_markdown(
    lead: str,
    sections: list[tuple[str, list[Bullet]]],
    entries: list[FeaturedEntry],
    listed: list[tuple[str, int]],
) -> str:
    """Assemble the full brief markdown: lead + sections + References + Also noticed.

    Each section renders as '## <heading>' followed by one markdown list item per grouped
    bullet; a bullet with inline related items gets an indented '  - Related: ...'
    sub-line. The [#n] -> card-link substitution is applied across the lead and
    every bullet; headings are rendered verbatim. The listed-only path passes the fixed
    lead line with zero sections.

    Args:
        lead: Opening paragraph (tokens still unsubstituted).
        sections: (heading, [Bullet, ...]) pairs in narrative order; each Bullet carries
            [#n] tokens and its inline related items.
        entries: Featured entries in reference order.
        listed: Low-relevance items as (title, card_id); section omitted when empty.

    Returns:
        The complete brief markdown document.
    """
    parts = [replace_refs(_normalize_dashes(lead), entries)]
    for heading, bullets in sections:
        lines: list[str] = []
        for bullet in bullets:
            # Flatten any embedded newline in the LLM-written bullet text so the
            # renderer always emits exactly one physical line per bullet -- mirrors
            # _card_link's title flattening. Without this, a bare column-0
            # continuation line survives into the markdown and the frontend's
            # line-based parser (parseBriefBullets) silently drops it, truncating
            # the bullet and losing any card ref on the continuation.
            one_line = bullet.text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            lines.append(f"- {replace_refs(_normalize_dashes(one_line), entries)}")
            if bullet.related:
                links = ", ".join(_card_link(t, cid) for t, cid in bullet.related)
                # Two-space indent nests the Related line under its bullet in markdown.
                lines.append(f"  - Related: {links}")
        parts.append(f"## {_normalize_dashes(heading)}\n\n" + "\n".join(lines))
    if entries:
        ref_lines = []
        for entry in entries:
            line = (
                f"- {_card_link(entry.title, entry.card_id)} — "
                f"{entry.origin}, {entry.published}, {entry.level}"
            )
            if entry.related:
                links = ", ".join(_card_link(t, cid) for t, cid in entry.related)
                line += f" (related: {links})"
            ref_lines.append(line)
        parts.append("## References\n" + "\n".join(ref_lines))
    if listed:
        also = "\n".join(f"- {_card_link(title, cid)}" for title, cid in listed)
        parts.append("## Also noticed\n" + also)
    return "\n\n".join(parts)
