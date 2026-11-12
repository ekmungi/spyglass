"""PDF support for the reader: a notice document, a capped download cache and text extraction.

A paper without an HTML edition (or any other PDF link) is shown through the built-in PDF viewer.
The reader document for it is a short notice plus the abstract; the PDF itself is downloaded on
demand into `<data_dir>/pdf_cache/<item id>.pdf` and served by the items API.
"""

import html as html_lib
import logging
import os
from collections.abc import Callable
from pathlib import Path

import httpx

from spyglass_service.documents import build_client
from spyglass_service.radar import netguard
from spyglass_service.radar.reader.sanitize import clean_html

logger = logging.getLogger(__name__)

# Largest PDF the app will download or serve. Papers with large figures, theses and scanned books
# run to the low hundreds of megabytes; the whole cache stays bounded by MAX_CACHE_BYTES.
MAX_PDF_BYTES = 150 * 1024 * 1024
# The whole PDF cache is kept under this size by deleting the least recently used files.
MAX_CACHE_BYTES = 1024 * 1024 * 1024
_PDF_MAGIC = b"%PDF"


# Redirect hops followed for a PDF; each target is checked before the request is made.
MAX_PDF_REDIRECTS = 5


class PdfError(Exception):
    """A PDF could not be fetched; the message is safe to show to the reader."""


def _too_large() -> str:
    """The reader-facing message for a PDF over the size limit; follows `MAX_PDF_BYTES`."""
    return f"The PDF is larger than {max(1, MAX_PDF_BYTES // (1024 * 1024))} MB."


def is_public_http_url(url: str) -> bool:
    """True for an http(s) URL whose host is public and resolves only to public addresses."""
    return netguard.is_public_url(url)


def pdf_result(url: str, title: str, abstract: str, *, notice: str, source_url: str,
               byline: str = "", site: str = "") -> dict:
    """The reader document for a work that is shown as a PDF: a notice and the abstract."""
    parts = [f"<p>{html_lib.escape(notice)}</p>"]
    if abstract.strip():
        parts.append("<h2>Abstract</h2>")
        parts.extend(f"<p>{html_lib.escape(p.strip())}</p>" for p in abstract.split("\n\n") if p.strip())
    cleaned = clean_html("".join(parts), source_url)
    return {
        "kind": "pdf", "html": cleaned, "title": title, "byline": byline, "site": site,
        "lead_image": "", "word_count": len(abstract.split()), "source_url": source_url,
        "alt_url": url,
    }


def cache_path(data_dir: Path, item_id: int) -> Path:
    """Where an item's downloaded PDF lives."""
    return data_dir / "pdf_cache" / f"{int(item_id)}.pdf"


def download_pdf(url: str, dest: Path, *, client: httpx.Client | None = None) -> None:
    """Stream `url` to `dest`, refusing non-PDF content and anything over `MAX_PDF_BYTES`.

    Raises `PdfError` with a short reason on any failure; a partial file is never left behind.
    """
    if not is_public_http_url(url):
        raise PdfError("This address cannot be fetched.")
    owns_client = client is None
    http = client or netguard.guard_client(build_client())
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        # Redirects are followed by hand so each hop is checked before it is requested.
        for _ in range(MAX_PDF_REDIRECTS):
            probe = http.send(http.build_request("GET", url), stream=True,
                              follow_redirects=False)
            target = probe.next_request.url if probe.is_redirect and probe.next_request else None
            probe.close()
            if target is None:
                break
            url = str(target)
            if not is_public_http_url(url):
                raise PdfError("This address cannot be fetched.")
        else:
            raise PdfError("The PDF address redirected too many times.")
        with http.stream("GET", url, follow_redirects=False) as resp:
            if resp.status_code != 200:
                raise PdfError(f"The PDF host answered HTTP {resp.status_code}.")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_PDF_BYTES:
                raise PdfError(_too_large())
            written, first = 0, True
            with tmp.open("wb") as handle:
                for chunk in resp.iter_bytes(64 * 1024):
                    if first:
                        first = False
                        if not chunk.startswith(_PDF_MAGIC):
                            raise PdfError("The address did not return a PDF.")
                    written += len(chunk)
                    if written > MAX_PDF_BYTES:
                        raise PdfError(_too_large())
                    handle.write(chunk)
            if written == 0:
                raise PdfError("The PDF was empty.")
        os.replace(tmp, dest)
    except httpx.HTTPError as exc:
        raise PdfError(f"Could not download the PDF ({exc.__class__.__name__}).") from exc
    finally:
        tmp.unlink(missing_ok=True)
        if owns_client:
            http.close()


def prune_cache(data_dir: Path, max_bytes: int | None = None, keep: Path | None = None) -> int:
    """Delete least recently used cached PDFs until the cache fits in `max_bytes`.

    `max_bytes` defaults to `MAX_CACHE_BYTES`. The `keep` file (the one just written) is never
    deleted. Returns the number of files removed; a file that cannot be removed is skipped.
    """
    limit = MAX_CACHE_BYTES if max_bytes is None else max_bytes
    folder = data_dir / "pdf_cache"
    if not folder.is_dir():
        return 0
    entries = []
    for path in folder.glob("*.pdf"):
        try:
            info = path.stat()
        except OSError:
            continue
        entries.append((info.st_mtime, info.st_size, path))
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, path in sorted(entries):  # oldest use first
        if total <= limit:
            break
        if keep is not None and path == keep:
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not prune %s: %s", path.name, exc.__class__.__name__)
            continue
        total -= size
        removed += 1
    return removed


def ensure_pdf(data_dir: Path, item_id: int, url: str, *,
               downloader: Callable[[str, Path], None] | None = None) -> Path:
    """Return the cached PDF of an item, downloading it first when it is not cached yet."""
    dest = cache_path(data_dir, item_id)
    if dest.is_file() and dest.stat().st_size > 0:
        os.utime(dest)  # a cache hit counts as use, so it is the last file to be pruned
        return dest
    (downloader or download_pdf)(url, dest)
    prune_cache(data_dir, keep=dest)
    return dest
