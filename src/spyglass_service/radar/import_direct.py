"""Direct import: a page or a selection sent in one step by the "Send to Spyglass" browser extension.

The extension reads the page the reader is looking at (after the reader's click) and posts it to
the service with the per-install key. There is no confirmation window, so this module adds the
rules that the window would otherwise give:

- a page never replaces an earlier copy that the reader sent in unless it has more words;
- a selection never replaces a full article: it becomes the document of an address only while that
  address has no readable document, and otherwise it is stored as a separate item;
- the reader's note is saved on the item in every case.

The work itself (address check, article extraction and sanitising, marking the item as sent in by
the reader, clearing the old judgement) is `importer.import_page`; nothing here uses the network.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.importer import Incoming, build_document, find_existing, import_page, validate_page_url
from spyglass_service.radar.models import ItemState, ReaderDoc, utcnow
from spyglass_service.radar.reader.build import _IMPORT_VIAS as IMPORT_CHANNELS
from spyglass_service.radar.sources._common import short_hash

__all__ = ["MAX_NOTE_CHARS", "MAX_TEXT_BYTES", "MAX_TITLE_CHARS", "RateLimiter", "import_direct"]

# Largest selection text (bytes) and the longest title and note (characters) the route accepts.
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TITLE_CHARS = 300
MAX_NOTE_CHARS = 500
# The channel recorded on an item sent by the extension.
VIA = "extension"
# Query parameter that gives a selection kept apart from its page an address of its own. The
# address normaliser drops a "#fragment", so the marker has to be a query parameter.
SELECTION_PARAM = "spyglass_selection"


class RateLimiter:
    """At most `limit` events in any `window_seconds`, counted in memory (restart forgets them)."""

    def __init__(self, limit: int = 30, window_seconds: float = 600.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._window, self._clock = limit, window_seconds, clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Record an event and return True, or return False (recording nothing) when over the limit."""
        now = self._clock()
        with self._lock:
            while self._events and now - self._events[0] >= self._window:
                self._events.popleft()
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


def _selection_url(url: str, content: str) -> str:
    """The address of a selection kept apart from its page: the page's address plus a short hash."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(SELECTION_PARAM, short_hash(content, 10))]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _doc_of(engine: Engine, item_id: int | None) -> ReaderDoc | None:
    """The item's stored reader document, or None."""
    if item_id is None:
        return None
    with Session(engine) as session:
        doc = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()
        if doc is not None:
            session.expunge(doc)
        return doc


def _readable(doc: ReaderDoc | None) -> bool:
    """True when the document holds text a reader could read (not a failed or empty one)."""
    return bool(doc and doc.status in ("ok", "partial") and doc.html and doc.word_count > 0)


def _sent_in_by_reader(engine: Engine, item_id: int) -> bool:
    """True when the reader sent this item's page in themselves (browser, paste, file, extension)."""
    with Session(engine) as session:
        state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
        return bool(state and state.captured_via in IMPORT_CHANNELS)


def _save_note(engine: Engine, item_id: int, note: str | None) -> None:
    """Store the reader's note on an item that already exists (a kept copy still gets the note)."""
    if not note:
        return
    with Session(engine) as session:
        state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
        if state is not None:
            state.user_note, state.updated_at = note, utcnow()
            session.add(state)
            session.commit()


def _result(engine: Engine, item_id: int, replaced: bool) -> dict:
    """The answer for the extension: the item, its title and the word count of its stored copy."""
    doc = _doc_of(engine, item_id)
    with Session(engine) as session:
        item = session.get(Item, item_id)
    title = (item.title if item is not None else "") or (doc.title if doc else "") or ""
    return {"item_id": item_id, "title": title, "words": doc.word_count if doc else 0, "replaced": replaced}


def _target(engine: Engine, url: str, kind: str, content: str) -> tuple[str, int | None]:
    """The address to import under and the item already stored for the page's own address.

    A selection goes to the page's own address while that address has no readable document;
    otherwise it gets an address of its own, so the full article is never replaced by a fragment.
    """
    existing = find_existing(engine, url)
    if kind == "selection" and _readable(_doc_of(engine, existing)):
        separate = _selection_url(url, content)
        return separate, find_existing(engine, separate)
    return url, existing


def _keeps_better_copy(engine: Engine, incoming: Incoming, url: str, existing: int | None) -> bool:
    """True when the reader's earlier copy has at least as many words as this page (keep it)."""
    kept = _doc_of(engine, existing)
    if existing is None or not _readable(kept) or kept.status != "ok":
        return False
    if not _sent_in_by_reader(engine, existing):
        return False
    return int(build_document(incoming, url).get("word_count") or 0) <= kept.word_count


def import_direct(engine: Engine, settings, *, url: str, title: str, html: str | None,
                  text: str | None, note: str | None, kind: str) -> dict:
    """Import what the extension sent and return `{"item_id", "title", "words", "replaced"}`.

    Raises ImportRefused (with a sentence fit for the reader) for an address that is not public
    http(s) or content with nothing readable in it; nothing is stored in that case.
    """
    page_url = validate_page_url(url)
    shown_title = title.strip()
    content = html if html is not None else (text or "")
    if kind == "selection":
        shown_title = f"Selection from: {shown_title or urlsplit(page_url).hostname or page_url}"
    target, existing = _target(engine, page_url, kind, content)
    incoming = Incoming(url=target, title=shown_title, html=html, text=text, via=VIA, note=note)
    if kind == "page" and _keeps_better_copy(engine, incoming, target, existing):
        _save_note(engine, existing, note)
        return _result(engine, existing, replaced=False)
    replaced = _readable(_doc_of(engine, existing))
    item_id = import_page(engine, settings, incoming)
    return _result(engine, item_id, replaced)
