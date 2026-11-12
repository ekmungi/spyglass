"""A durable store for the files the reader sent in: pictures and PDFs.

The image and PDF caches are trimmed to a size limit, least recently used first, which is right for
copies of web pages that can be fetched again. A picture or PDF the reader sent in (through Slack, or
with the "add file" button) exists nowhere else, so it lives here instead: `<data_dir>/media/from_you`,
one file per item named by the item's number (`7.png`, `12.pdf`). Nothing trims this folder; a file
leaves it only when its item is deleted.

Safety:
- the file name is built from an integer item number, never from text in a request;
- the file type is read from the file's first bytes (PNG, JPEG, WebP or PDF; never SVG, which can
  carry script), not from its name;
- a picture is served only for the address of the item whose document shows it, and only up to
  `MAX_PICTURE_BYTES`.
"""

import logging
import os
import re
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar import media_proxy
from spyglass_service.radar.models import ItemState, ReaderDoc

logger = logging.getLogger(__name__)

# The largest picture served from the store: above the 20 MB Slack allows, so every picture that was
# accepted can be shown. (Pictures fetched from web pages are capped lower, at 8 MB.)
MAX_PICTURE_BYTES = 25 * 1024 * 1024
# The words every reader document built for a file the reader added starts with.
PDF_ADDED = "This is the PDF you added"
MISSING_PICTURE = "This picture is no longer stored in Spyglass. Send it in again to see it here."

# (file suffix, media type) by the first bytes of the file.
_PDF = ("pdf", "application/pdf")
_IMAGES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_FIGURE = re.compile(r"<figure\b.*?</figure>", re.IGNORECASE | re.DOTALL)


def folder(data_dir: Path) -> Path:
    """The store's folder under the data directory."""
    return Path(data_dir) / "media" / "from_you"


def sniff(head: bytes) -> tuple[str, str] | None:
    """(suffix, media type) of PNG, JPEG, WebP or PDF bytes; None for anything else."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", _IMAGES["png"]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg", _IMAGES["jpg"]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", _IMAGES["webp"]
    if head.startswith(b"%PDF"):
        return _PDF
    return None


def _path(data_dir: Path, item_id: int, suffix: str) -> Path:
    """The file for an item; only an integer and a known suffix go into the name."""
    return folder(data_dir) / f"{int(item_id)}.{suffix}"


def remove(data_dir: Path, item_id: int) -> int:
    """Delete the item's stored file (whatever its type); the number of files removed."""
    removed = 0
    for suffix in (*_IMAGES, _PDF[0]):
        try:
            _path(data_dir, item_id, suffix).unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("could not remove a stored file of item %s", int(item_id), exc_info=True)
    return removed


def put(data_dir: Path, item_id: int, data: bytes) -> str:
    """Store the item's file, replacing an earlier one; returns its media type.

    Raises ValueError when the bytes are not a PNG, JPEG, WebP or PDF.
    """
    kind = sniff(data[:16])
    if kind is None:
        raise ValueError("only PNG, JPEG, WebP and PDF files are stored")
    suffix, media = kind
    remove(data_dir, item_id)
    target = _path(data_dir, item_id, suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_bytes(data)
    os.replace(partial, target)
    return media


def find(data_dir: Path, item_id: int) -> tuple[Path, str] | None:
    """(path, media type) of the item's stored file, with the type read from its bytes."""
    for suffix in (*_IMAGES, _PDF[0]):
        path = _path(data_dir, item_id, suffix)
        try:
            with path.open("rb") as handle:
                kind = sniff(handle.read(16))
        except OSError:
            continue
        if kind is not None:
            return path, kind[1]
    return None


def size_bytes(data_dir: Path) -> int:
    """The total size of the stored files (0 when there are none)."""
    total = 0
    try:
        for path in folder(data_dir).iterdir():
            try:
                total += path.stat().st_size if path.is_file() else 0
            except OSError:
                continue
    except OSError:
        return 0
    return total


def image_for_address(engine: Engine, data_dir: Path, url: str) -> tuple[bytes, str] | None:
    """(bytes, media type) of the stored picture whose document shows `url`; None when there is none.

    The address is only compared with the lead image of stored reader documents; nothing from it
    reaches a file name. A stored PDF, or a picture over the size cap, is never returned.
    """
    if not url or len(url) > media_proxy.MAX_URL_CHARS:
        return None
    with Session(engine) as session:
        ids = session.exec(select(ReaderDoc.item_id).where(ReaderDoc.lead_image == url).limit(5)).all()
    for item_id in ids:
        found = find(data_dir, item_id)
        if found is None or not found[1].startswith("image/"):
            continue
        try:
            if found[0].stat().st_size > MAX_PICTURE_BYTES:
                continue
            return found[0].read_bytes(), found[1]
        except OSError:
            continue
    return None


def _move_picture(data_dir: Path, item_id: int, url: str) -> bool:
    """Move the picture at `url` from the image cache into the store; True when it was moved."""
    cache = Path(data_dir) / "img_cache"
    hit = media_proxy.cache_get(cache, url)
    if hit is None or sniff(hit[0][:16]) is None:
        return False
    put(data_dir, item_id, hit[0])
    for victim in media_proxy._paths(cache, url):  # noqa: SLF001 -- the cache's own file names
        victim.unlink(missing_ok=True)
    return True


def _move_pdf(data_dir: Path, item_id: int) -> bool:
    """Move the item's PDF from the PDF cache into the store; True when it was moved."""
    source = Path(data_dir) / "pdf_cache" / f"{int(item_id)}.pdf"
    try:
        data = source.read_bytes()
        put(data_dir, item_id, data)
        source.unlink()
    except (OSError, ValueError):
        return False
    return True


def move_from_caches(engine: Engine, data_dir: Path) -> dict:
    """Move pictures and PDFs the reader sent in, still in the caches, into the store.

    Safe to repeat: an item is moved only while its file is still in a cache, so a second run finds
    nothing. Only items sent in by the reader are looked at: pictures whose document shows the
    address they were sent from, and PDFs whose document is the "PDF you added" notice. Returns
    `{"images": n, "pdfs": n}`.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(ReaderDoc.item_id, ReaderDoc.kind, ReaderDoc.lead_image, ReaderDoc.source_url,
                   ReaderDoc.html)
            .join(ItemState, ItemState.item_id == ReaderDoc.item_id)
            .where(ItemState.from_user.is_(True))).all()  # type: ignore[attr-defined]
    moved = {"images": 0, "pdfs": 0}
    for item_id, kind, lead, source, html in rows:
        try:
            if kind == "pdf" and PDF_ADDED in (html or ""):
                moved["pdfs"] += _move_pdf(data_dir, item_id)
            elif lead and lead == source and _move_picture(data_dir, item_id, lead):
                moved["images"] += 1
        except OSError:
            logger.warning("could not move the file of item %s", item_id, exc_info=True)
    return moved


def _is_picture_document(reader: dict) -> bool:
    """True for the document of a picture the reader sent in: one figure, shown from its own address."""
    lead = reader.get("lead_image")
    return bool(lead) and lead == reader.get("source_url") and "<figure" in (reader.get("html") or "")


def with_missing_picture_notice(reader: dict | None, data_dir: Path, item_id: int) -> dict | None:
    """The reader block, with a plain sentence in place of the picture when its file is gone.

    Only the document of a picture the reader sent in is looked at. The picture counts as present
    when it is in the store or still in the image cache.
    """
    if not reader or not _is_picture_document(reader):
        return reader
    if find(data_dir, item_id) is not None:
        return reader
    if media_proxy.cache_has(Path(data_dir) / "img_cache", reader["lead_image"]):
        return reader
    html = _FIGURE.sub(f"<p>{MISSING_PICTURE}</p>", reader.get("html") or "", count=1)
    return {**reader, "html": html, "lead_image": ""}

