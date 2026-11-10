"""Disk-download of a bookmark's document, and best-effort page-title repair.

Split out of documents.py to keep that module's `fetch_fulltext`
conductor under the project's 400-line file cap. This module owns the two units
that write a document to disk (`fetch_document`, used by the MCP fetch_document
tool) and the one that repairs a source-truncated item title (`fetch_page_title`,
used by api_pages.py and fulltext.py). Neither is part of the fetch_fulltext
in-memory acquire+extract path -- both use their own network fetch, independent
of fetch_acquire/extractors.*.
"""

import re
from collections.abc import Callable
from pathlib import Path

import httpx

# Characters not allowed in Windows filenames.
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


def _slug(url: str) -> str:
    """A short, Windows-safe filename stem derived from the URL's last segment."""
    tail = url.rstrip("/").split("/")[-1] or "document"
    tail = _ILLEGAL.sub("", tail).split("?")[0]
    return (tail[:80] or "document").strip(".")


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF using pypdf (imported lazily). Used only by fetch_document
    (disk-based path); the in-memory fetch_fulltext path uses extractors.pdf.extract_pdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _strip_html(text: str) -> str:
    """Plain text from an HTML page."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _extract_title_default(html: str) -> str | None:
    """Default page-title extractor: trafilatura metadata (imported lazily)."""
    import trafilatura

    metadata = trafilatura.extract_metadata(html)
    return metadata.title if metadata else None


def fetch_page_title(
    url: str,
    client: httpx.Client | None = None,
    extractor: Callable[[str], str | None] | None = None,
) -> str | None:
    """The page's own title from the ORIGINAL url (no arXiv pdf rewrite).

    Used to repair source-truncated item titles (Raindrop clips long ones).
    Returns None on any failure -- repair is best-effort, never an error.
    """
    # Imported lazily (not at module scope) to avoid a documents<->documents_download
    # import cycle: documents.py re-exports fetch_page_title/fetch_document from here,
    # so this module cannot import documents at load time.
    from .documents import build_client

    owns_client = client is None
    client = client or build_client()
    try:
        response = client.get(url)
        if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            return None
        return (extractor or _extract_title_default)(response.text)
    except httpx.HTTPError:
        return None
    finally:
        if owns_client:
            client.close()


def fetch_document(
    url: str,
    dest_dir: Path,
    client: httpx.Client | None = None,
    pdf_extractor: Callable[[Path], str] | None = None,
) -> dict:
    """Download url into dest_dir; return {path, content_type, text}.

    PDFs are saved as-is and their text extracted; other pages are saved as HTML
    and stripped to plain text. Raises on a non-success response.
    """
    # Lazy import -- see fetch_page_title's comment above for why.
    from .documents import build_client, normalize_url

    target_url = normalize_url(url)
    owns_client = client is None
    client = client or build_client()
    try:
        response = client.get(target_url)
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download document: HTTP {response.status_code}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    content_type = response.headers.get("content-type", "")
    is_pdf = "pdf" in content_type.lower() or target_url.lower().endswith(".pdf")

    if is_pdf:
        path = dest_dir / f"{_slug(target_url)}.pdf"
        path.write_bytes(response.content)
        extractor = pdf_extractor or _extract_pdf_text
        text = extractor(path)
    else:
        path = dest_dir / f"{_slug(target_url)}.html"
        path.write_text(response.text, encoding="utf-8")
        text = _strip_html(response.text)

    return {"path": str(path), "content_type": content_type, "text": text}
