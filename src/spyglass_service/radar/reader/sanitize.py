"""The HTML security boundary of the reader.

`clean_html` turns the markup of an arbitrary web page into a small, safe subset that the
frontend injects as HTML. It runs in two steps. A tolerant pre-pass (BeautifulSoup) does the
structural chores that need to see sibling attributes: promoting lazy-load image attributes,
dropping tracking pixels, unwrapping in-page anchors and pruning empty wrappers. Then `nh3`
(the Rust `ammonia` sanitizer) applies an explicit allowlist and an attribute filter that
absolutises and validates every URL. Nothing the pre-pass produces is trusted: the sanitizer
sees all of it, and its output is returned untouched.
"""

import re
from urllib.parse import urljoin, urlsplit

import nh3
from bs4 import BeautifulSoup, Comment, Tag

# --- Allowlist ---------------------------------------------------------------------------

_STRUCTURE = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code",
    "hr", "br", "div", "span", "section", "article",
}
_INLINE = {"a", "em", "strong", "b", "i", "u", "s", "sub", "sup", "mark", "abbr", "time", "kbd"}
_MEDIA = {"img", "figure", "figcaption", "picture", "source"}
_TABLES = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col"}
_DISCLOSURE = {"details", "summary"}
_MATHML = {
    "math", "mrow", "mi", "mn", "mo", "msup", "msub", "msubsup", "mfrac", "msqrt", "mroot",
    "mtext", "mspace", "mtable", "mtr", "mtd", "mover", "munder", "munderover", "semantics",
    "annotation", "mstyle", "mpadded", "menclose",
}
ALLOWED_TAGS = _STRUCTURE | _INLINE | _MEDIA | _TABLES | _DISCLOSURE | _MATHML

# Presentation attributes MathML needs to lay out fractions, big operators and matrices.
_MATH_ATTRS = {
    "display", "alttext", "mathvariant", "displaystyle", "scriptlevel", "stretchy", "fence",
    "separator", "lspace", "rspace", "form", "accent", "accentunder", "largeop", "movablelimits",
    "linethickness", "columnalign", "rowalign", "columnspacing", "rowspacing", "columnlines",
    "rowlines", "frame", "width", "height", "depth", "voffset", "notation", "encoding",
}
# MathML attributes that set a length. A page could ask for a huge one to blow the layout up, so
# only a short number with a unit, or a named space such as `thinmathspace`, is kept.
_MATH_LENGTHS = {"width", "height", "depth", "voffset", "lspace", "rspace", "linethickness"}
_MATH_LENGTH = re.compile(
    r"-?\d{1,3}(?:\.\d{1,3})?(?:em|ex|px|pt|rem|%)?|(?:negative)?(?:very){0,2}(?:thin|medium|thick)mathspace")
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height", "srcset", "sizes"},
    "source": {"srcset", "sizes", "media", "type"},
    "abbr": {"title"},
    "time": {"datetime"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start"},
    "li": {"value"},
    "details": {"open"},
    # `class` survives only on code blocks, and only as a language hint (see _keep_classes).
    "code": {"class"},
    "pre": {"class"},
    **{tag: _MATH_ATTRS for tag in _MATHML},
}

# Elements removed together with everything inside them. Anything not allowlisted and not
# listed here is unwrapped (its text is kept), which is what we want for unknown wrappers.
_DROP_WITH_CONTENT = {
    "script", "style", "noscript", "iframe", "object", "embed", "svg", "template", "textarea",
    "select", "button", "input", "form", "head", "title", "canvas", "audio", "video", "applet",
    "frameset", "frame", "noframes", "xmp", "plaintext", "link", "meta", "base", "dialog",
    "option", "optgroup", "datalist", "fieldset", "nav",
}

_URL_SCHEMES = {"http", "https", "mailto"}
_WEB_SCHEMES = {"http", "https"}
# The only class tokens that survive: a code-language hint. Any other class would pick up the
# application's own utility classes (fixed, inset-0, z-50 ...) and could paint over the interface.
_CLASS_TOKEN = re.compile(r"(?:language|lang)-[A-Za-z0-9+#.-]{1,32}")
_LAZY_SRC = ("data-src", "data-lazy-src", "data-original", "data-lazy", "data-hi-res-src")
_LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")
_VOID_OR_MEDIA = {"img", "picture", "math", "table", "hr", "br", "pre", "source", "figure"}
_PRUNABLE = {"div", "span", "section", "article", "p", "a", "figure", "figcaption", "li", "ul",
             "ol", "blockquote", "em", "strong", "b", "i", "u", "s", "details", "sup", "sub"}
_PIXEL_MAX = 2  # an image this small in both dimensions is a tracking pixel


# --- URL helpers ---------------------------------------------------------------------------


def _absolute(value: str, base_url: str, schemes: set[str]) -> str | None:
    """Resolve `value` against `base_url`; return None unless the result's scheme is allowed.

    Control characters and whitespace inside the scheme are removed first because browsers
    ignore them (`java\\tscript:` is `javascript:` to a browser), so the scheme check must too.
    """
    cleaned = re.sub(r"[\x00-\x20\x7f]+", "", value)
    if not cleaned:
        return None
    try:
        joined = urljoin(base_url, cleaned) if base_url else cleaned
        scheme = urlsplit(joined).scheme.lower()
    except ValueError:
        return None
    return joined if scheme in schemes else None


def _parse_srcset(value: str) -> list[tuple[str, str]]:
    """Split a srcset into (url, descriptor) pairs following the HTML parsing rules.

    A URL may itself contain commas (image CDNs do this), so a candidate ends at the first
    whitespace after its URL and the descriptor runs to the next comma.
    """
    pairs: list[tuple[str, str]] = []
    pos, n = 0, len(value)
    while pos < n:
        while pos < n and (value[pos].isspace() or value[pos] == ","):
            pos += 1
        start = pos
        while pos < n and not value[pos].isspace():
            pos += 1
        url = value[start:pos]
        if not url:
            break
        if url.endswith(","):
            pairs.append((url.rstrip(","), ""))
            continue
        desc_start = pos
        while pos < n and value[pos] != ",":
            pos += 1
        pairs.append((url, value[desc_start:pos].strip()))
    return pairs


def _absolute_srcset(value: str, base_url: str) -> str | None:
    """Absolutise every candidate of a srcset, dropping unsafe ones; None if none survive."""
    kept: list[str] = []
    for url, descriptor in _parse_srcset(value):
        absolute = _absolute(url, base_url, _WEB_SCHEMES)
        if absolute is None or not re.fullmatch(r"(?:\d+(?:\.\d+)?[wx])?", descriptor):
            continue
        kept.append(f"{absolute} {descriptor}".strip())
    return ", ".join(kept) if kept else None


def _keep_classes(value: str) -> str | None:
    """Keep only code-language class tokens (`language-python`, `lang-c`), else None."""
    tokens = [t for t in value.split() if _CLASS_TOKEN.fullmatch(t)]
    return " ".join(tokens) if tokens else None


def _make_filter(base_url: str):
    """Build the nh3 attribute filter that absolutises URLs and sanitises class values."""

    def attribute_filter(tag: str, attr: str, value: str) -> str | None:
        """Return the value to keep for one attribute, or None to drop it."""
        if attr in ("href", "src"):
            schemes = _URL_SCHEMES if attr == "href" else _WEB_SCHEMES
            return _absolute(value, base_url, schemes)
        if attr == "srcset":
            return _absolute_srcset(value, base_url)
        if attr == "class":
            return _keep_classes(value) if tag in ("code", "pre") else None
        if attr in _MATH_LENGTHS and tag in _MATHML:
            return value.strip() if _MATH_LENGTH.fullmatch(value.strip()) else None
        return value

    return attribute_filter


# --- Pre-pass ------------------------------------------------------------------------------


def _int_attr(tag: Tag, name: str) -> int | None:
    """An integer pixel attribute ('1', '1px'), or None when absent or not numeric."""
    match = re.match(r"\s*(\d+)", str(tag.get(name, "")))
    return int(match.group(1)) if match else None


def promote_lazy_images(soup: BeautifulSoup) -> None:
    """Copy lazy-load attributes (data-src ...) over src/srcset so the real image is used."""
    for tag in soup.find_all(["img", "source"]):
        for name in _LAZY_SRC:
            if tag.get(name) and tag.name == "img":
                tag["src"] = tag[name]
                break
        for name in _LAZY_SRCSET:
            if tag.get(name):
                tag["srcset"] = tag[name]
                break


def _drop_tracking_pixels(soup: BeautifulSoup, base_url: str) -> None:
    """Remove 1x1 images and images that have no usable http(s) source (data: URLs go too)."""
    for img in soup.find_all("img"):
        width, height = _int_attr(img, "width"), _int_attr(img, "height")
        tiny = width is not None and height is not None and width <= _PIXEL_MAX and height <= _PIXEL_MAX
        has_src = _absolute(str(img.get("src", "")), base_url, _WEB_SCHEMES) is not None
        has_srcset = _absolute_srcset(str(img.get("srcset", "")), base_url) is not None
        if tiny or not (has_src or has_srcset):
            img.decompose()


def _unwrap_dead_links(soup: BeautifulSoup, base_url: str) -> None:
    """Replace in-page anchors and links with an unusable target by their content.

    Ids are stripped by the sanitiser, so a `#fragment` link could not resolve anyway.
    """
    for link in soup.find_all("a"):
        href = str(link.get("href", "")).strip()
        if href.startswith("#") or _absolute(href, base_url, _URL_SCHEMES) is None:
            link.unwrap()


def _is_empty(tag: Tag) -> bool:
    """True when the element holds no visible text and no media."""
    if tag.name not in _PRUNABLE:
        return False
    if tag.find(list(_VOID_OR_MEDIA)) is not None:
        return False
    return not tag.get_text(strip=True)


def _prune_empty(soup: BeautifulSoup) -> None:
    """Remove empty wrappers, innermost first, until nothing more can go."""
    changed = True
    while changed:
        changed = False
        for tag in reversed(soup.find_all(list(_PRUNABLE))):
            if tag.parent is not None and _is_empty(tag):
                tag.decompose()
                changed = True


def _prepare(html: str, base_url: str) -> BeautifulSoup:
    """Parse `html` and apply the structural clean-ups that need attribute context."""
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(list(_DROP_WITH_CONTENT)):
        tag.decompose()
    promote_lazy_images(soup)
    _drop_tracking_pixels(soup, base_url)
    _unwrap_dead_links(soup, base_url)
    _prune_empty(soup)
    return soup


# --- Public API ----------------------------------------------------------------------------


def clean_html(html: str, base_url: str) -> str:
    """Sanitise `html` for the reader and make every URL absolute against `base_url`.

    Only the allowlisted tags and attributes survive; scripts, styles, frames, forms, event
    handlers, `javascript:` and every `data:` URL are removed. Links open in a new tab with
    `rel="noopener noreferrer"`; images load lazily without sending a referrer. Returns an
    empty string for empty input. Never raises on malformed markup.
    """
    if not html or not html.strip():
        return ""
    soup = _prepare(html, base_url)
    cleaned = nh3.clean(
        str(soup),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_make_filter(base_url),
        clean_content_tags=_DROP_WITH_CONTENT,
        url_schemes=_URL_SCHEMES,
        url_relative="pass_through",
        link_rel="noopener noreferrer",
        set_tag_attribute_values={
            "a": {"target": "_blank"},
            "img": {"loading": "lazy", "referrerpolicy": "no-referrer", "decoding": "async"},
        },
        strip_comments=True,
    )
    return cleaned.strip()
