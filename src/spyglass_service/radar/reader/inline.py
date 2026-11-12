"""Keep inline code and the spaces around inline elements intact through the main-text extractor.

The extractor (trafilatura) has three habits that damage running text: it turns an inline
`<code>` into a block-level `<pre>` (which splits the sentence in two), it trims the whitespace
next to inline elements ("our<a>previous book</a>"), and it writes tables as `<row>`/`<cell>`
elements that are not HTML. `protect_inline` hides inline code and those spaces behind marker
characters before extraction, and `restore_inline` puts real markup back afterwards.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Elements next to which a space matters ("our <a>previous book</a>"); used to find empty ones.
_INLINE_TAGS = ("a", "b", "strong", "i", "em", "u", "s", "mark", "small", "sub", "sup", "code",
                "cite", "abbr", "q", "span", "font", "time", "label", "kbd", "var", "samp", "del", "ins")
# Elements that start or end a line of text: no space is needed next to them.
_NON_INLINE = frozenset({
    "html", "head", "body", "p", "div", "section", "article", "header", "footer", "nav", "aside",
    "main", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td",
    "th", "caption", "blockquote", "pre", "figure", "figcaption", "h1", "h2", "h3", "h4", "h5",
    "h6", "hr", "br", "form", "fieldset", "details", "summary", "script", "style", "noscript",
    "iframe", "video", "audio", "canvas", "svg", "textarea",
})
# Text inside these keeps its whitespace exactly.
_VERBATIM_TAGS = ("script", "style", "pre", "textarea")
# Private-use characters standing in for a space and for the two ends of an inline code span.
# The extractor trims whitespace but never a visible character, so they survive it.
_SPACE_MARK = ""
_CODE_OPEN = ""
_CODE_CLOSE = ""
_CODE_SPAN = re.compile(f"{_CODE_OPEN}(.*?){_CODE_CLOSE}", re.DOTALL)


def _is_inline(node: object) -> bool:
    """True for a tag that sits inside a line of text (not a paragraph, list item, cell...)."""
    return isinstance(node, Tag) and node.name not in _NON_INLINE


def _touches_inline(node: NavigableString, forward: bool) -> bool:
    """True when an inline element sits right after (forward) or before this text node.

    A node at the edge of its own inline wrapper counts through the wrapper, however deeply
    nested: in "<span><span>with our </span></span><a>previous book</a>" the space belongs to
    the inner span but sits next to the link.
    """
    step = "next_sibling" if forward else "previous_sibling"
    current = node
    while True:
        sibling = getattr(current, step)
        if sibling is not None:
            return _is_inline(sibling)
        parent = current.parent
        if parent is None or not _is_inline(parent):
            return False
        current = parent


def _mark_inline_code(soup: BeautifulSoup) -> None:
    """Replace each inline `<code>` (one outside a `<pre>`) with its text between code markers."""
    for code in soup.find_all("code"):
        if code.find_parent("pre") is None:
            code.replace_with(NavigableString(_CODE_OPEN + code.get_text() + _CODE_CLOSE))


def _mark_blank_inline_elements(soup: BeautifulSoup) -> None:
    """Replace an inline element that holds only whitespace (`<a> </a>`) with a space marker."""
    for tag in soup.find_all(_INLINE_TAGS):
        text = tag.get_text()
        if text and not text.strip() and tag.find(["img", "svg", "picture"]) is None:
            tag.replace_with(NavigableString(_SPACE_MARK))


def _space_adjacent_elements(soup: BeautifulSoup) -> None:
    """Put a space between two inline elements that touch with a word end on both sides.

    A page can separate "<span>Provided by</span><a>HPE</a>" with a style margin only; without
    the style the two words run together.
    """
    for tag in soup.find_all(_INLINE_TAGS):
        nxt = tag.next_sibling
        if not (_is_inline(nxt) and nxt.name in _INLINE_TAGS):
            continue
        before, after = tag.get_text(), nxt.get_text()
        if before[-1:].isalnum() and after[:1].isalnum() and tag.find("img") is None:
            tag.insert_after(NavigableString(_SPACE_MARK))


def protect_inline(raw_html: str) -> str:
    """The page with inline code and the whitespace next to inline elements hidden behind markers.

    Only text that has words in it, or whitespace between two inline elements, is touched, so
    whitespace between block elements stays as it is.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    _wrap_pre_contents(soup)  # a bare <pre> would otherwise be turned into a block quote
    _mark_inline_code(soup)
    _mark_blank_inline_elements(soup)
    _space_adjacent_elements(soup)
    for node in soup.find_all(string=True):
        text = str(node)
        if type(node) is not NavigableString or node.find_parent(_VERBATIM_TAGS) or _SPACE_MARK in text:
            continue
        if not text.strip():
            if text and _touches_inline(node, forward=False) and _touches_inline(node, forward=True):
                node.replace_with(NavigableString(_SPACE_MARK))
            continue
        head, core, tail = text[:len(text) - len(text.lstrip())], text.strip(), text[len(text.rstrip()):]
        marked_head = _SPACE_MARK if head and _touches_inline(node, forward=False) else head
        marked_tail = _SPACE_MARK if tail and _touches_inline(node, forward=True) else tail
        if (marked_head, marked_tail) != (head, tail):
            node.replace_with(NavigableString(marked_head + core + marked_tail))
    return str(soup)


def _restore_tables(html: str) -> str:
    """Rename the extractor's `<row>`/`<cell>` elements to `<tr>`/`<td>` (`<th>` for head cells)."""
    if "<row" not in html and "<cell" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("row"):
        row.name, row.attrs = "tr", {}
    for cell in soup.find_all("cell"):
        cell.name, cell.attrs = ("th" if cell.get("role") == "head" else "td"), {}
    return str(soup)


def restore_inline(extracted: str) -> str:
    """Extractor output with real `<code>` spans, real table tags and ordinary spaces again."""
    restored = _CODE_SPAN.sub(r"<code>\1</code>", extracted)
    restored = restored.replace(_CODE_OPEN, "").replace(_CODE_CLOSE, "")
    return _restore_tables(restored).replace(_SPACE_MARK, " ")


def _wrap_pre_contents(soup: BeautifulSoup) -> None:
    """Put the contents of every `<pre>` that has no `<code>` child inside one."""
    for pre in soup.find_all("pre"):
        if pre.find("code") is None:
            code = soup.new_tag("code")
            code.extend(list(pre.contents))
            pre.append(code)


def wrap_block_code(html: str) -> str:
    """HTML where every `<pre>` holds a `<code>` element, so block code has one shape."""
    if "<pre" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    _wrap_pre_contents(soup)
    return str(soup)
