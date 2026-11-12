"""Make outside text safe to show as one line of plain text inside a prompt or a request.

Headlines come from feeds, notes and project names from the reader, and all of them end up in text
that another program reads. `clean_line` turns control characters (newlines and tabs included)
into spaces, removes invisible formatting characters (zero-width and direction overrides, which
can disguise what text says), collapses whitespace and cuts the result to a limit.
"""

import unicodedata

ELLIPSIS = "…"


def clean_line(value: object, limit: int) -> str:
    """`value` as one plain line of at most `limit` characters ("" for None)."""
    if value is None:
        return ""
    out: list[str] = []
    for char in str(value):
        category = unicodedata.category(char)
        if category == "Cc":
            out.append(" ")
        elif category != "Cf":
            out.append(char)
    text = " ".join("".join(out).split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + ELLIPSIS


def quoted_line(value: object, limit: int) -> str:
    """`clean_line` with double quotes turned into single ones, for text shown inside quotes."""
    return clean_line(str(value).replace('"', "'") if value is not None else None, limit)
