"""Build, store and return the reader document of an item.

`ensure_reader_doc` is the single entry point. It routes an item's URL to the right builder
(arXiv paper, YouTube video, GitHub repository, PDF, or the generic article extractor), stores
the sanitised result in the `ReaderDoc` table, and makes sure the item's plain text is in the
engine's Content table so the assessment pipeline, search and the assistant can read it.
Failures are stored as a document with status "failed" and a short human reason; they are
never raised to the caller. A passing failure (the network is down) is returned the same way but
not stored, so the next open tries again.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.content_store import get_fulltext, store_fulltext
from spyglass_service.extractors.pdf import extract_pdf
from spyglass_service.models import Item
from spyglass_service.radar.models import ItemState, ReaderDoc, utcnow
from spyglass_service.radar.reader.arxiv import arxiv_id, build_arxiv
from spyglass_service.radar.reader.assemble import build_article_fields
from spyglass_service.radar.reader.github import build_github, github_repo
from spyglass_service.radar.reader.http import BuildFailure, Fetcher, Page, make_fetcher
from spyglass_service.radar.reader.pdf import pdf_result
from spyglass_service.radar.reader.paywall import PARTIAL_NOTICE
from spyglass_service.radar.reader.text import plain_abstract, plain_text
from spyglass_service.radar.reader.video import Transcriber, build_video, youtube_id

logger = logging.getLogger(__name__)

# Documents made by other parts of the app (an email body, a pasted note) are never rebuilt.
_FOREIGN_KINDS = ("email", "note")
# A failed fetch is retried on the next open only after this long, so a dead link does not
# trigger a slow fetch ladder every time it is clicked.
_RETRY_FAILED_AFTER = timedelta(hours=1)
# The channels (`ItemState.captured_via`) through which the reader hands over a page they already
# have open: the browser bookmark button, pasted text, an uploaded file, the browser extension.
# Their stored document is the reader's own copy and is only replaced by a better automatic one.
_IMPORT_VIAS = ("browser", "paste", "file", "text", "extension")
# Stored status of a paywalled preview: readable, but marked as partial.
_PARTIAL = "partial"

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _item_lock(item_id: int) -> threading.Lock:
    """One lock per item so two simultaneous opens build the document once."""
    with _locks_guard:
        return _locks.setdefault(item_id, threading.Lock())


def reader_dict(row: ReaderDoc) -> dict:
    """The reader block of the item-detail shape, from a stored row.

    A stored "partial" document (a paywalled preview) is returned with status "ok" so every
    client treats it as readable, plus `partial: true` and the notice to show above it.
    """
    partial = row.status == _PARTIAL
    return {
        "kind": row.kind, "html": row.html, "title": row.title, "byline": row.byline,
        "site": row.site, "lead_image": row.lead_image, "word_count": row.word_count,
        "source_url": row.source_url, "alt_url": row.alt_url,
        "status": "ok" if partial else row.status, "error": None if partial else row.error,
        "partial": partial, "notice": (row.error or PARTIAL_NOTICE) if partial else None,
    }


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp read from SQLite as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_fresh(row: ReaderDoc) -> bool:
    """True when the stored document should be returned without refetching."""
    if row.status in ("ok", _PARTIAL):
        return True
    if row.status == "failed":
        return datetime.now(UTC) - _aware(row.fetched_at) < _RETRY_FAILED_AFTER
    return False


def _pdf_text(page: Page) -> str:
    """Best-effort plain text of a fetched PDF page; "" when it cannot be read."""
    if page.ok and page.is_markdown:
        return page.text.strip()  # the Jina rung already extracted the PDF's text
    if not page.ok or not page.is_pdf or isinstance(page.body, str):
        return ""
    try:
        return extract_pdf(page.body).strip()
    except Exception:  # noqa: BLE001 -- a broken PDF only costs us the search text
        logger.exception("PDF text extraction failed for %s", page.url)
        return ""


def _generic(item: Item, fetch: Fetcher) -> dict:
    """Fetch an arbitrary URL and build an article (or PDF) document from it."""
    page = fetch(item.url)
    if not page.ok:
        raise BuildFailure(page.error or "The page could not be fetched.",
                           transient=page.transient)
    if page.is_pdf:
        fields = pdf_result(
            page.url, item.title, plain_abstract(item.summary),
            notice="This document is a PDF, shown below.", source_url=item.url,
        )
        text = _pdf_text(page)
        return {**fields, "text": text, "word_count": len(text.split()) or fields["word_count"]}
    return build_article_fields(item.url, item.title, page)


def _route(item: Item, fetch: Fetcher, stored_text: str, transcriber: Transcriber | None) -> dict:
    """Pick the builder for an item's URL and return the reader fields (and optional text)."""
    aid = arxiv_id(item.url)
    if aid:
        # A paper without an HTML edition keeps its abstract as the stored text: downloading and
        # reading the whole PDF would make the first open of the item take many seconds.
        return build_arxiv(aid, title=item.title, abstract=plain_abstract(item.summary), fetch=fetch)
    video = youtube_id(item.url)
    if video:
        return build_video(video, url=item.url, title=item.title, origin=item.origin or "",
                           stored_text=stored_text, transcriber=transcriber)
    repo = github_repo(item.url)
    if repo:
        fields = build_github(repo[0], repo[1], url=item.url, fetch=fetch)
        if fields is not None:
            return fields
    return _generic(item, fetch)


def _stored_text(engine: Engine, item_id: int) -> str:
    """The item's stored plain text, or "" when there is none or it is not usable."""
    stored = get_fulltext(engine, item_id)
    return (stored["markdown"] or "") if stored and stored["status"] == "ok" else ""


def _store_text(engine: Engine, item_id: int, text: str, source_url: str, kind: str) -> None:
    """Store `text` in the Content table unless a longer text is already stored there."""
    if not text.strip():
        return
    if len(_stored_text(engine, item_id)) >= len(text):
        return
    store_fulltext(engine, item_id=item_id, markdown=text, source_url=source_url,
                   content_type="text/html", status="ok", detected_type=f"reader:{kind}")


def _save(engine: Engine, item_id: int, fields: dict) -> ReaderDoc:
    """Insert or update the item's ReaderDoc from builder fields; returns the stored row."""
    with Session(engine) as session:
        row = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()
        row = row or ReaderDoc(item_id=item_id)
        row.kind = fields.get("kind", "article")
        row.html = fields.get("html", "")
        row.title = fields.get("title") or None
        row.byline = fields.get("byline") or None
        row.site = fields.get("site") or None
        row.lead_image = fields.get("lead_image") or None
        row.word_count = int(fields.get("word_count") or 0)
        row.source_url = fields.get("source_url")
        row.alt_url = fields.get("alt_url")
        row.status = fields.get("status", "ok")
        row.error = fields.get("error")
        row.fetched_at = utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def _row_fields(fields: dict) -> dict:
    """Builder fields as ReaderDoc column values (for a row that is shown but not stored)."""
    return {"kind": fields.get("kind", "article"), "html": fields.get("html", ""),
            "title": fields.get("title") or None, "word_count": int(fields.get("word_count") or 0),
            "source_url": fields.get("source_url"), "status": fields.get("status", "ok"),
            "error": fields.get("error")}


def _is_imported(engine: Engine, item_id: int) -> bool:
    """True when the reader brought this item's page in themselves (see `_IMPORT_VIAS`)."""
    with Session(engine) as session:
        state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
        return bool(state and state.captured_via in _IMPORT_VIAS)


def _is_better(fields: dict, kept: ReaderDoc) -> bool:
    """True when rebuilt fields are readable ("ok") and have more words than the kept copy."""
    return fields.get("status", "ok") == "ok" and int(fields.get("word_count") or 0) > kept.word_count


def _failure_fields(item: Item, reason: str) -> dict:
    """Fields of a stored failed document."""
    return {"kind": "article", "html": "", "title": item.title, "word_count": 0,
            "source_url": item.url, "status": "failed", "error": reason[:300]}


def ensure_reader_doc(
    engine: Engine, settings, item_id: int, *, force: bool = False,
    fetch: Fetcher | None = None, transcriber: Transcriber | None = None,
) -> dict:
    """Return the reader document of `item_id`, building and storing it when needed.

    An existing ok document is returned as is unless `force`; a document of kind "email" or
    "note" (made elsewhere) is always returned as is; a failed one is retried after an hour,
    except a passing failure, which is not stored and so is retried on the next open. A forced
    refresh keeps a page the reader imported themselves unless the rebuild is "ok" with more words.
    `fetch` and `transcriber` are injectable for tests. Raises `LookupError` only for an
    unknown item id; every fetch or parsing problem is stored as status "failed" instead.
    """
    with _item_lock(item_id):
        with Session(engine) as session:
            item = session.get(Item, item_id)
            existing = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()
            if existing is not None:
                session.expunge(existing)
        if item is None:
            raise LookupError(f"item {item_id} not found")
        if existing is not None and existing.kind in _FOREIGN_KINDS:
            return reader_dict(existing)
        if existing is not None and not force and _is_fresh(existing):
            return reader_dict(existing)
        # A forced refresh never swaps the reader's own imported copy for a worse automatic one.
        imported = existing if (existing is not None and force and existing.status == "ok"
                                and _is_imported(engine, item_id)) else None
        fetcher = fetch or make_fetcher(settings, engine)
        try:
            fields = _route(item, fetcher, _stored_text(engine, item_id), transcriber)
        except BuildFailure as exc:
            fields = _failure_fields(item, str(exc))
            if imported is not None:
                return reader_dict(imported)
            if exc.transient:
                # A passing problem (network down, name not found): show the failure now but
                # store nothing, so the next open tries again instead of waiting an hour.
                return reader_dict(ReaderDoc(item_id=item_id, **_row_fields(fields)))
        except Exception:  # noqa: BLE001 -- the reader must degrade, never raise to the caller
            logger.exception("reader build failed for item %s", item_id)
            fields = _failure_fields(item, "The page could not be turned into a reader view.")
        if imported is not None and not _is_better(fields, imported):
            return reader_dict(imported)
        text = fields.pop("text", None)
        row = _save(engine, item_id, fields)
        if row.status in ("ok", _PARTIAL):
            _store_text(engine, item_id, text or plain_text(row.html), item.url, row.kind)
        return reader_dict(row)
