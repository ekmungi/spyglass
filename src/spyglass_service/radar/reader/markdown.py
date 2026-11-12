"""A small markdown converter and the parser for a text-rendering fetch service's output.

When the fetch ladder falls back to a service that renders a page as text, the answer is markdown
with a short header ("Title: ...", "URL Source: ...", "Markdown Content:"), not HTML.
`parse_fetch_markdown` splits that header from the body, and `markdown_to_html` turns the body
into real HTML: headings, paragraphs, emphasis, links, images, nested lists, block quotes, fenced
and inline code, and simple tables. Everything is escaped on the way in; the sanitiser
(`clean_html`) still runs on the result.
"""

import html as html_lib
import re
from collections.abc import Callable
from dataclasses import dataclass

# --- the service header ------------------------------------------------------------------------

_HEADER_LINE = re.compile(
    r"^(Title|URL Source|Final URL|Published Time|Warning|Description|Author|Markdown Content):[ \t]*(.*)$"
)
_TARGET_ERROR = re.compile(r"Target URL returned error (\d{3})", re.IGNORECASE)
# Service notices that say nothing about the page itself and are dropped silently.
_NOISE_NOTICE = re.compile(r"cached snapshot", re.IGNORECASE)


@dataclass(frozen=True)
class FetchMarkdown:
    """The parts of a fetch service answer: the header fields and the markdown body."""

    body: str
    title: str = ""
    source_url: str = ""
    final_url: str = ""
    published: str = ""
    warnings: tuple[str, ...] = ()
    target_error: int | None = None


def parse_fetch_markdown(text: str) -> FetchMarkdown:
    """Split a fetch service answer into header fields and body.

    Text that does not start with a "Title:" line is returned as the body unchanged. Warnings
    that only describe the service (a cached snapshot) are dropped; the others are kept so the
    caller can tell an error page from an article. The header is never part of the body.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None or not lines[first].startswith("Title:"):
        return FetchMarkdown(body=(text or "").strip())
    fields: dict[str, str] = {}
    warnings: list[str] = []
    body_start = len(lines)
    for index in range(first, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        found = _HEADER_LINE.match(line)
        if not found:
            body_start = index
            break
        key, value = found.group(1), found.group(2).strip()
        if key == "Markdown Content":
            lines[index] = value  # the body may start on the marker line itself
            body_start = index
            break
        if key == "Warning":
            warnings.append(value)
        else:
            fields.setdefault(key, value)
    kept = tuple(w for w in warnings if not _NOISE_NOTICE.search(w))
    error = next((int(m.group(1)) for w in kept if (m := _TARGET_ERROR.search(w))), None)
    return FetchMarkdown(
        body="\n".join(lines[body_start:]).strip(), title=fields.get("Title", ""),
        source_url=fields.get("URL Source", ""), final_url=fields.get("Final URL", ""),
        published=fields.get("Published Time", ""), warnings=kept, target_error=error,
    )


# --- inline ------------------------------------------------------------------------------------

_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_URL = r"((?:[^\s()]|\([^\s()]*\))+)(?:\s+&quot;.*?&quot;)?"
_IMAGE = re.compile(r"!\[([^\]]*)\]\(" + _URL + r"\)")
_LINK = re.compile(r"\[((?:[^\[\]]|<img [^>]*>)+?)\]\(" + _URL + r"\)")
_AUTOLINK = re.compile(r"&lt;(https?://[^\s&]+)&gt;")
_STRONG = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_EMPHASIS = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])|(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_IMAGE_ALT_PREFIX = re.compile(r"^Image \d+(?::\s*)?")
# Placeholders (private-use characters) for text that emphasis must not touch.
_OPEN, _CLOSE = "", ""
_PLACEHOLDER = re.compile(_OPEN + r"(\d+)" + _CLOSE)
# A link that follows a letter, or is followed by four or more letters, lost its space in the service.
_LETTER_BEFORE = re.compile(r"[A-Za-z0-9,;:]$")
_LETTERS_AFTER = re.compile(r"^[A-Za-z]{4,}")


def _inline(raw: str) -> str:
    """HTML for one line (or paragraph) of markdown inline syntax."""
    stash: list[str] = []

    def hold(value: str) -> str:
        """Keep `value` aside and return a placeholder for it."""
        stash.append(value)
        return f"{_OPEN}{len(stash) - 1}{_CLOSE}"

    def code(found: re.Match) -> str:
        """A code span, escaped and held back from emphasis."""
        inner = found.group(2)
        if inner.startswith(" ") and inner.endswith(" ") and inner.strip():
            inner = inner[1:-1]
        return hold(f"<code>{html_lib.escape(inner)}</code>")

    text = _CODE_SPAN.sub(code, raw)
    text = _ESCAPED.sub(lambda m: hold(html_lib.escape(m.group(1))), text)
    text = html_lib.escape(text)
    text = _IMAGE.sub(lambda m: hold(
        f'<img alt="{_IMAGE_ALT_PREFIX.sub("", m.group(1)).strip()}" src="{m.group(2)}">'), text)
    text = _link_pass(text, hold)
    text = _AUTOLINK.sub(lambda m: hold(f'<a href="{m.group(1)}">{m.group(1)}</a>'), text)
    text = _STRONG.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _EMPHASIS.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    text = _STRIKE.sub(r"<del>\1</del>", text)
    while _PLACEHOLDER.search(text):  # held pieces can contain placeholders (an image in a link)
        text = _PLACEHOLDER.sub(lambda m: stash[int(m.group(1))], text)
    return text


def _link_pass(text: str, hold: Callable[[str], str]) -> str:
    """Turn `[text](url)` into anchors, restoring a space the service dropped around a word."""
    pieces: list[str] = []
    cursor = 0
    for found in _LINK.finditer(text):
        before, after = text[cursor:found.start()], text[found.end():]
        label = re.sub(r"<[^>]+>|" + _OPEN + r"\d+" + _CLOSE, "", found.group(1)).strip()
        starts_with_word = bool(label) and label[0].isalpha()
        glued_before = starts_with_word and _LETTER_BEFORE.search(before or "")
        glued_after = label[-1:].isalpha() and _LETTERS_AFTER.match(after)
        anchor = hold(f'<a href="{found.group(2)}">{found.group(1)}</a>')
        pieces.append(before + (" " if glued_before else "") + anchor + (" " if glued_after else ""))
        cursor = found.end()
    return "".join(pieces) + text[cursor:]


# --- blocks ------------------------------------------------------------------------------------

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")


def _indent(line: str) -> int:
    """Number of leading spaces of `line` (a tab counts as four)."""
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _is_table_start(lines: list[str], i: int) -> bool:
    """True when `lines[i]` is a table header row followed by a separator row."""
    return (i + 1 < len(lines) and "|" in lines[i] and "|" in lines[i + 1]
            and bool(_TABLE_SEPARATOR.match(lines[i + 1])) and "-" in lines[i + 1])


def _starts_block(lines: list[str], i: int) -> bool:
    """True when `lines[i]` begins a block that may interrupt a paragraph."""
    line = lines[i]
    if _FENCE.match(line) or _HEADING.match(line) or _QUOTE.match(line) or _is_table_start(lines, i):
        return True
    item = _ITEM.match(line)
    return bool(item and (item.group(2) in "-*+" or item.group(2).startswith("1")))


def _cells(row: str) -> list[str]:
    """The cells of a pipe-separated table row."""
    stripped = row.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _table(lines: list[str], i: int) -> tuple[str, int]:
    """HTML for the table starting at `lines[i]` and the index after it."""
    head = "".join(f"<th>{_inline(c)}</th>" for c in _cells(lines[i]))
    j, rows = i + 2, []
    while j < len(lines) and lines[j].strip() and "|" in lines[j]:
        rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(lines[j])) + "</tr>")
        j += 1
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>", j


def _list(lines: list[str], i: int) -> tuple[str, int]:
    """HTML for the list starting at `lines[i]` (nested lists included) and the index after it."""
    first = _ITEM.match(lines[i])
    base, ordered = len(first.group(1).expandtabs(4)), first.group(2)[0].isdigit()
    items: list[list[str]] = []
    j = i
    while j < len(lines):
        line = lines[j]
        if not line.strip():
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            nxt = _ITEM.match(lines[k]) if k < len(lines) else None
            continues = k < len(lines) and (_indent(lines[k]) > base or (
                nxt and _indent(lines[k]) == base and nxt.group(2)[0].isdigit() == ordered))
            if not continues:
                break
            j = k
            continue
        item = _ITEM.match(line)
        if item and _indent(line) == base:
            if item.group(2)[0].isdigit() != ordered:
                break
            items.append([item.group(3)])
        elif item and _indent(line) < base:
            break
        elif _indent(line) > base or (items and lines[j - 1].strip()):
            items[-1].append(line.expandtabs(4)[min(_indent(line), base + 2):])
        else:
            break
        j += 1
    rendered = "".join(f"<li>{_item_html(item_lines)}</li>" for item_lines in items)
    start = ""
    if ordered and (number := int(re.match(r"\d+", first.group(2)).group())) != 1:
        start = f' start="{number}"'
    tag = "ol" if ordered else "ul"
    return f"<{tag}{start}>{rendered}</{tag}>", j


def _item_html(item_lines: list[str]) -> str:
    """The inside of one list item: its first paragraph is inline, nested blocks follow."""
    html = _blocks(item_lines)
    return re.sub(r"^<p>(.*?)</p>", r"\1", html, count=1, flags=re.DOTALL)


def _paragraph(lines: list[str], i: int) -> tuple[str, int]:
    """HTML for the paragraph (or setext heading) starting at `lines[i]` and the index after it."""
    parts: list[str] = []
    j = i
    while j < len(lines) and lines[j].strip():
        if j > i and (_RULE.match(lines[j]) or _starts_block(lines, j)):
            break
        underline = _SETEXT.match(lines[j]) if j > i else None
        if underline:
            level = 1 if underline.group(1)[0] == "=" else 2
            return f"<h{level}>{_inline(' '.join(parts))}</h{level}>", j + 1
        parts.append(lines[j].rstrip("\n"))
        j += 1
    joined = ""
    for part in parts:
        hard = part.endswith("  ") or part.endswith("\\")
        joined += part.strip().removesuffix("\\") + ("\n" if hard else " ")
    body = _inline(joined.strip()).replace("\n", "<br>")
    return f"<p>{body}</p>", j


def _blocks(lines: list[str]) -> str:
    """HTML for a list of markdown lines, block by block."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif fence := _FENCE.match(line):
            marker, code = fence.group(1), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1  # the closing fence (or the end of the text for an unclosed one)
            out.append(f"<pre><code>{html_lib.escape(chr(10).join(code))}</code></pre>")
        elif heading := _HEADING.match(line):
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
        elif _RULE.match(line):
            out.append("<hr>")
            i += 1
        elif _QUOTE.match(line):
            quoted = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append(f"<blockquote>{_blocks(quoted)}</blockquote>")
        elif _is_table_start(lines, i):
            html, i = _table(lines, i)
            out.append(html)
        elif _ITEM.match(line):
            html, i = _list(lines, i)
            out.append(html)
        else:
            html, i = _paragraph(lines, i)
            out.append(html)
    return "".join(out)


def markdown_to_html(markdown: str) -> str:
    """HTML for `markdown`: headings, paragraphs, emphasis, links, images, lists, quotes, code, tables.

    The text is escaped first, so raw HTML in the markdown is shown as text, never run.
    """
    return _blocks((markdown or "").replace("\r\n", "\n").split("\n"))
