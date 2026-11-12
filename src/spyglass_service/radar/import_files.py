"""Turn what the reader brings in by hand (pasted text, a saved page, a PDF) into page content.

These are pure conversions with no network and no database: the importer decides what to store.
A saved web page arrives as `.html`/`.htm` (decoded with the charset it declares) or as `.mhtml`
(a MIME archive; the first `text/html` part is the page). A PDF is recognised by its signature,
not by its name, and its text is read by the same extractor the reader uses for fetched PDFs.
"""

import email
import email.policy
import html as html_lib
import re
from pathlib import PurePath

from bs4 import UnicodeDammit

from spyglass_service.extractors.pdf import extract_pdf

# Largest file accepted, in megabytes: the same limit the reader uses for PDFs it downloads, and
# the number the interface and every message about it are built from. The byte limit follows it.
MAX_FILE_MB = 150
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
# Largest web page read from a file or a paste, counted in UTF-8 bytes. A saved page with its
# pictures inlined can be big; anything larger than this is not an article.
MAX_PAGE_BYTES = 15 * 1024 * 1024
# A PDF may put its signature anywhere in the first kilobyte.
_PDF_SIGNATURE = b"%PDF-"
_HTML_EXTENSIONS = (".html", ".htm")
_MHTML_EXTENSIONS = (".mhtml", ".mht")
# Tags that mark pasted text as HTML source rather than prose.
_HTML_TAG = re.compile(r"<(?:!doctype|html|body|article|main|section|div|p|h[1-6]|ul|ol|li|table|"
                       r"blockquote|pre|br|img|a|span|figure)\b[^>]*>", re.IGNORECASE)
_BLANK_LINE = re.compile(r"\n[ \t]*\n+")
# A first line longer than this is a paragraph, not a headline.
_TITLE_MAX = 200


class ImportRefused(ValueError):
    """The content cannot be imported; the message says why in a sentence fit for the reader."""


def looks_like_html(text: str) -> bool:
    """Whether pasted text is HTML source (it holds at least two structural tags)."""
    return len(_HTML_TAG.findall(text[:200_000])) >= 2


def text_to_html(text: str) -> str:
    """Plain text as escaped HTML: blank lines separate paragraphs, other line breaks stay."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [block.strip() for block in _BLANK_LINE.split(normalised) if block.strip()]
    return "".join(
        "<p>" + "<br>".join(html_lib.escape(line.strip()) for line in block.split("\n")) + "</p>"
        for block in paragraphs
    )


def first_line_title(text: str) -> str:
    """The first line of pasted text when it is short enough to be a headline, else ""."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2 or len(lines[0]) > _TITLE_MAX:
        return ""
    return lines[0]


def decode_html_bytes(data: bytes) -> str:
    """The text of a saved web page, decoded with its byte-order mark or declared charset."""
    decoded = UnicodeDammit(data, is_html=True).unicode_markup
    return decoded if decoded is not None else data.decode("utf-8", "replace")


def mhtml_html(data: bytes) -> str:
    """The web page inside an `.mhtml` archive: its first `text/html` part, decoded.

    Browsers often leave the charset off the part's header and declare it in the page itself,
    so a part without a usable charset is decoded like a saved `.html` file.
    """
    message = email.message_from_bytes(data, policy=email.policy.default)
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        raw = part.get_payload(decode=True) or b""
        charset = part.get_content_charset()
        if charset:
            try:
                return raw.decode(charset, "replace")
            except LookupError:
                pass  # an unknown charset name: fall back to what the page declares
        return decode_html_bytes(raw)
    raise ImportRefused("This archive holds no web page.")


def is_pdf(data: bytes) -> bool:
    """Whether the bytes carry a PDF signature in their first kilobyte."""
    return _PDF_SIGNATURE in data[:1024]


def file_kind(filename: str, data: bytes) -> str:
    """"pdf", "html" or "mhtml" for an uploaded file; ImportRefused for anything else."""
    if not data:
        raise ImportRefused("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ImportRefused(f"The file is larger than {MAX_FILE_MB} MB.")
    suffix = PurePath(filename or "").suffix.lower()
    if suffix == ".pdf":
        if not is_pdf(data):
            raise ImportRefused("This file is named .pdf but is not a PDF.")
        return "pdf"
    if suffix in _HTML_EXTENSIONS:
        return "html"
    if suffix in _MHTML_EXTENSIONS:
        return "mhtml"
    raise ImportRefused("Choose a .pdf, .html or .mhtml file saved from your browser.")


def page_from_file(filename: str, data: bytes) -> str:
    """The HTML of an uploaded `.html` or `.mhtml` file, checked against the page size limit."""
    kind = file_kind(filename, data)
    if kind == "pdf":
        raise ImportRefused("This is a PDF, not a web page.")
    page = mhtml_html(data) if kind == "mhtml" else decode_html_bytes(data)
    check_page_size(page)
    return page


def check_page_size(page: str) -> None:
    """Refuse a web page over `MAX_PAGE_BYTES`."""
    if len(page.encode("utf-8", "surrogatepass")) > MAX_PAGE_BYTES:
        raise ImportRefused("This page is larger than 15 MB and cannot be read.")


def pdf_text(data: bytes) -> str:
    """The text of a PDF ("" for a scan or a damaged file)."""
    return extract_pdf(data).strip()
