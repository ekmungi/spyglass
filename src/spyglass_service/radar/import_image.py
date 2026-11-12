"""A picture the reader sends in (for example through Slack) as an item whose document shows it.

The reader document is one figure with the picture and, when the reader wrote a few words with it,
those words below. The picture itself lives in the store of files the reader sent in (`from_you_store`), which cache
trimming never touches: the document's `<img>` points at the item's own address, the reader's
browser asks this service for that address, and the stored bytes are served. Nothing is fetched
from anywhere.
Only PNG, JPEG and WebP are accepted (never SVG, which can carry script), and the caller checks the
bytes before they get here.
"""

import html as html_lib
from pathlib import Path

from spyglass_service.radar import from_you_store
from spyglass_service.radar.reader.sanitize import clean_html

# The picture formats that can be shown, with their media types.
IMAGE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


def image_fields(url: str, title: str, caption: str | None) -> dict:
    """The reader fields of a picture item (plus "text", the words the assistant can read)."""
    name = title.strip() or "Picture"
    parts = [f'<figure><img src="{html_lib.escape(url, quote=True)}" alt="{html_lib.escape(name, quote=True)}"></figure>']
    if caption and caption.strip():
        parts.append(f"<p>{html_lib.escape(caption.strip())}</p>")
    return {
        "kind": "article", "html": clean_html("".join(parts), url), "title": name, "byline": "",
        "site": "", "lead_image": url, "word_count": len((caption or "").split()),
        "source_url": url, "alt_url": None, "text": (caption or "").strip() or name,
    }


def keep_image(data_dir: Path, item_id: int, data: bytes) -> None:
    """Put the picture's bytes in the store of files the reader sent in, under the item's number."""
    from_you_store.put(Path(data_dir), item_id, data)
