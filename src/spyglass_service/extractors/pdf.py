"""In-memory PDF -> text extraction (PyMuPDF/fitz), injectable for tests.

Moved out of documents.py. Uses PyMuPDF/fitz rather than pypdf: fitz is the fast
digital-PDF path, chosen because a planned scanned-PDF OCR fallback would need page
rendering and a planned feature needs embedded-image extraction -- one self-contained lib
for text + render + image-extract, no native binary. The separate disk-download path
(documents_download.py) still uses pypdf.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _extract_pdf_text_from_bytes(content: bytes) -> str:
    """Extract text from in-memory PDF bytes using PyMuPDF/fitz (imported lazily).

    Concatenates get_text() across all pages. Returns "" (rather than raising) when
    the bytes are not a readable PDF -- a fetch failure is data the conductor can
    record as an empty result, not a crash. The failure is still logged (not just
    swallowed) so a corrupt-PDF fetch is diagnosable instead of looking like a
    genuinely empty page.
    """
    import fitz

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        logger.warning(
            "PDF parse failed (fitz.open); treating as empty extraction", exc_info=True
        )
        return ""

    try:
        return "\n".join(page.get_text() for page in doc).strip()
    finally:
        doc.close()


def extract_pdf(content: bytes, extractor: Callable[[bytes], str] | None = None) -> str:
    """Text from in-memory PDF bytes.

    Uses PyMuPDF/fitz by default; the extractor is injectable so tests need neither
    the network nor the real library (mirrors extract_markdown's seam). Returns ""
    when nothing usable is extracted.
    """
    extract = extractor or _extract_pdf_text_from_bytes
    return extract(content) or ""
