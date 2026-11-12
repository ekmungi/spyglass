"""Article images fetched by the service, so the reader's browser never contacts their sites.

A reader document's images are rewritten (see `reader/media.py`) to `/api/radar/img?u=<address>`.
This module serves that address:

- Only addresses that appear in a stored reader document (its HTML or its lead image) are
  fetched, so the endpoint is not an open proxy. Positive answers are remembered in memory.
- The fetch uses the guarded page-fetch client: public addresses only on every redirect hop,
  GET only, no cookies or credential headers, the generic agent.
- Only `image/*` answers pass, never SVG (which can carry script), at most 8 MB.
- Images are cached on disk under `<data_dir>/img_cache` with hashed file names, kept under
  500 MB by removing the least recently used files.
- A picture the reader sent in is not cached but kept in its own store (`from_you_store`), which is
  checked first and never trimmed.
"""

import hashlib
import html
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import Engine, func, or_
from sqlmodel import Session, select

from spyglass_service.radar import netguard
from spyglass_service.radar.models import ReaderDoc

logger = logging.getLogger(__name__)

# The largest image served, and the most the cache may hold on disk.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CACHE_BYTES = 500 * 1024 * 1024
# Longest address accepted, and seconds allowed for one image fetch.
MAX_URL_CHARS = 4096
IMAGE_TIMEOUT = 20.0
# Known-address answers remembered in memory (positive answers only).
_MEMO_SIZE = 4096

# A 1x1 transparent GIF: served for anything refused, so page layouts do not break.
PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00"
         b"\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

# Replaced in tests: builds the guarded client an image is fetched with.
_client_factory = lambda: netguard.page_client(timeout=IMAGE_TIMEOUT)  # noqa: E731

_memo: "OrderedDict[str, bool]" = OrderedDict()
_memo_lock = threading.Lock()
_stamp_lock = threading.Lock()
_last_stamp = [0.0]


def clear_memo() -> None:
    """Forget the remembered known addresses (tests)."""
    with _memo_lock:
        _memo.clear()


def _is_web(url: str) -> bool:
    """True for an absolute http(s) address of acceptable length."""
    parts = urlsplit(url or "")
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname) \
        and len(url) <= MAX_URL_CHARS


def is_known_image(engine: Engine, url: str) -> bool:
    """True when `url` appears in some stored reader document's HTML or is its lead image."""
    with _memo_lock:
        if url in _memo:
            _memo.move_to_end(url)
            return True
    escaped = html.escape(url, quote=True)
    with Session(engine) as session:
        found = session.exec(select(ReaderDoc.id).where(or_(
            func.instr(ReaderDoc.html, url) > 0, func.instr(ReaderDoc.html, escaped) > 0,
            ReaderDoc.lead_image == url)).limit(1)).first()
    if found is None:
        return False
    with _memo_lock:
        _memo[url] = True
        while len(_memo) > _MEMO_SIZE:
            _memo.popitem(last=False)
    return True


def _image_type(header: str) -> str | None:
    """The media type when it is an image other than SVG, else None."""
    kind = (header or "").split(";", 1)[0].strip().lower()
    if not kind.startswith("image/") or kind == "image/svg+xml":
        return None
    return kind


def fetch_image(url: str) -> tuple[bytes, str] | None:
    """(bytes, media type) of the image at `url`, or None when refused or failed."""
    try:
        with _client_factory() as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return None
                kind = _image_type(response.headers.get("content-type", ""))
                declared = response.headers.get("content-length", "")
                if kind is None or (declared.isdigit() and int(declared) > MAX_IMAGE_BYTES):
                    return None
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks), kind
    except httpx.HTTPError as exc:
        logger.info("image fetch refused or failed: %s", exc.__class__.__name__)
        return None


def _paths(folder: Path, url: str) -> tuple[Path, Path]:
    """The cache files for `url`: the image and its media type."""
    name = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return folder / f"{name}.img", folder / f"{name}.type"


def _touch(path: Path) -> None:
    """Mark a cache file as just used (strictly later than the previous mark)."""
    with _stamp_lock:
        stamp = max(time.time(), _last_stamp[0] + 0.001)
        _last_stamp[0] = stamp
    os.utime(path, (stamp, stamp))


def cache_get(folder: Path, url: str) -> tuple[bytes, str] | None:
    """The cached image for `url`, marked as used; None when absent or unreadable."""
    image, kind = _paths(folder, url)
    try:
        body, media = image.read_bytes(), kind.read_text(encoding="utf-8").strip()
        _touch(image)
    except OSError:
        return None
    return (body, media) if _image_type(media) else None


def cache_has(folder: Path, url: str) -> bool:
    """True when the image cache holds `url` (nothing is read and the entry is not marked as used)."""
    return _paths(folder, url)[0].is_file()


def _enforce_bound(folder: Path) -> None:
    """Remove the least recently used images until the cache fits in `CACHE_BYTES`."""
    files = []
    for path in folder.glob("*.img"):
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _, size, _ in files)
    for _mtime, size, path in sorted(files):
        if total <= CACHE_BYTES:
            break
        for victim in (path, path.with_suffix(".type")):
            victim.unlink(missing_ok=True)
        total -= size


def cache_put(folder: Path, url: str, body: bytes, kind: str) -> None:
    """Store an image for `url`, then keep the cache within its bound."""
    folder.mkdir(parents=True, exist_ok=True)
    image, media = _paths(folder, url)
    media.write_text(kind, encoding="utf-8")
    image.write_bytes(body)
    _touch(image)
    _enforce_bound(folder)


def serve(engine: Engine, data_dir: Path, url: str) -> tuple[bytes, str] | None:
    """The image for a proxy request, or None when it must be refused (see the module doc)."""
    if not _is_web(url):
        return None
    # A picture the reader sent in lives in its own store, which cache trimming never touches.
    from spyglass_service.radar import from_you_store  # here: the store imports this module

    owned = from_you_store.image_for_address(engine, Path(data_dir), url)
    if owned is not None:
        return owned
    folder = Path(data_dir) / "img_cache"
    hit = cache_get(folder, url)
    if hit is not None:
        return hit
    if not is_known_image(engine, url):
        return None
    got = fetch_image(url)
    if got is None:
        return None
    try:
        cache_put(folder, url, *got)
    except OSError:
        logger.warning("could not cache an image", exc_info=True)
    return got
