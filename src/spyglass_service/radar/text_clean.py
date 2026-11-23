"""Make outside text safe to show as plain text inside a prompt or a request.

Headlines come from feeds, notes and project names from the reader, and all of them end up in text
that another program reads. `clean_line` turns control characters (newlines and tabs included)
into spaces, removes invisible formatting characters (zero-width and direction overrides, which
can disguise what text says), collapses whitespace and cuts the result to a limit. `clean_text`
does the same for a note of several lines but keeps its line breaks.
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


# Line and paragraph separators that count as a line break in a note, besides \r and \n.
_LINE_SEPARATORS = {" ", " "}


def clean_text(value: object, limit: int) -> str:
    """`value` as plain text of at most `limit` characters that keeps its line breaks.

    For a note the reader writes over several lines (the note for the filing session). Line
    breaks of any kind become "\\n"; other control characters become spaces and invisible
    formatting characters go, as in `clean_line`. Spaces collapse within each line, each line is
    trimmed, runs of blank lines shrink to one blank line, and blank lines at either end go.
    """
    if value is None:
        return ""
    raw = str(value).replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for char in raw:
        category = unicodedata.category(char)
        if char == "\n" or char in _LINE_SEPARATORS:
            out.append("\n")
        elif category == "Cc":
            out.append(" ")
        elif category != "Cf":
            out.append(char)
    lines = [" ".join(line.split()) for line in "".join(out).split("\n")]
    kept: list[str] = []
    for line in lines:
        # Keep a blank line only after a line with text: at most one blank line in a row.
        if line or (kept and kept[-1]):
            kept.append(line)
    text = "\n".join(kept).strip("\n")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + ELLIPSIS


def quoted_line(value: object, limit: int) -> str:
    """`clean_line` with double quotes turned into single ones, for text shown inside quotes."""
    return clean_line(str(value).replace('"', "'") if value is not None else None, limit)
