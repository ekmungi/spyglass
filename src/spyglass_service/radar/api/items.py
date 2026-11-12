"""Radar items API: the feed, the item detail with its reader document, and reader actions.

Endpoints (all under /api/radar): GET /feed, GET /items/{id}, POST /items/{id}/reader/refresh,
GET /items/{id}/pdf, POST /items/{id}/signal, POST|DELETE /items/{id}/save and
POST /items/{id}/vote. Handlers are plain functions so FastAPI runs them in its worker
threadpool: building a reader document (a network fetch that can take many seconds) never
blocks the event loop.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlmodel import Session, select

from spyglass_service.content_routing import classify_url
from spyglass_service.models import Feed, Item
from spyglass_service.radar.api.item_quality import (
    infer_kinds, story_sources, unique_related,
)
from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.radar.feed_conditions import feed_conditions
from spyglass_service.radar.feed_views import feed_view
from spyglass_service.radar.models import (
    Assessment, AssistThread, ItemState, ReaderDoc, Signal, utcnow,
)
from spyglass_service.radar.reader.arxiv import arxiv_id, pdf_url
from spyglass_service.radar.reader.build import ensure_reader_doc
from spyglass_service.radar import from_you_store
from spyglass_service.radar.reader.media import proxied_reader
from spyglass_service.radar.reader.pdf import PdfError, ensure_pdf, is_public_http_url
from spyglass_service.radar.serialize import radar_items

logger = logging.getLogger(__name__)
router = APIRouter()

# Largest single "dwell" report accepted, so a stuck timer cannot inflate reading time.
MAX_DWELL_SECONDS = 120
_RELATED_CANDIDATES = 25
_RELATED_SHOWN = 5


class SignalBody(BaseModel):
    """A reader behaviour report: opened the item, spent time on it, or expanded a section."""

    kind: Literal["open", "dwell", "expand"]
    value: int | str | None = None

    @field_validator("value")
    @classmethod
    def _bounded(cls, value: int | str | None) -> int | str | None:
        """Keep free-text values short; dwell seconds are checked against `kind` in the handler."""
        if isinstance(value, str) and len(value) > 200:
            raise ValueError("value is too long")
        return value


class VoteBody(BaseModel):
    """The more/less-like-this vote; null clears it."""

    vote: Literal["more", "less"] | None = None


# --- helpers -------------------------------------------------------------------------------


def _naive_utc(value: datetime) -> datetime:
    """Timestamp as the naive UTC the database stores."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _as_datetime(value: datetime | str) -> datetime:
    """A sort key as read back from SQLite (a datetime, or text for some expressions)."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _require_item(session: Session, item_id: int) -> Item:
    """The item, or a 404."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


def _state_row(session: Session, item_id: int) -> ItemState:
    """The item's reader-state row, created (not yet committed) when missing."""
    row = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
    if row is None:
        row = ItemState(item_id=item_id)
        session.add(row)
    return row


def _state_dict(session: Session, item_id: int) -> dict:
    """The `state` block of the item's RadarItem."""
    items = radar_items(session, [item_id])
    return items[0]["state"] if items else {}


# --- feed ----------------------------------------------------------------------------------


@router.get("/feed")
def get_feed(
    request: Request,
    section: str | None = None,
    kind: str | None = None,
    tier: str | None = None,
    saved: bool | None = None,
    from_user: bool | None = None,
    filed: bool | None = None,
    filing: Literal["waiting"] | None = None,
    missed: bool | None = None,
    watch_group: str | None = None,
    q: str | None = None,
    before: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List items newest first, with filters, a `before` cursor and a total count.

    The default view hides tier "out", unjudged items older than two days and items from disabled
    feeds; `tier=all` lifts the first two rules. `q` matches stored full text or the title.
    `missed` and `watch_group` are saved views with their own rules (see radar/feed_views.py).
    """
    engine = request.app.state.engine
    cursor: datetime | None = None
    if before:
        try:
            cursor = _naive_utc(datetime.fromisoformat(before.replace("Z", "+00:00")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="before must be an ISO timestamp") from exc
    sort_key = func.coalesce(Item.published_at, Item.fetched_at)
    view = feed_view(engine, missed=missed, watch_group=watch_group, sort_key=sort_key)
    conds = feed_conditions(section=section, kind=kind, tier=tier, saved=saved,
                            from_user=from_user, q=q, engine=engine, sort_key=sort_key,
                            filed=filed, waiting=filing == "waiting", extra=view.conditions)
    base = (
        select(Item.id, sort_key.label("sk"))
        .select_from(Item)
        .join(Assessment, Assessment.item_id == Item.id, isouter=True)
        .join(ItemState, ItemState.item_id == Item.id, isouter=True)
        .join(Feed, Feed.feed_url == Item.feed_url, isouter=True)
        .where(*conds)
    )
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(base.subquery())).one()
        paged = base.where(sort_key < cursor) if cursor and not view.single_page else base
        rows = list(session.exec(paged.order_by(*view.order).limit(limit + 1)).all())
        # A view ordered by score has no date cursor: it is one page, however many items match.
        page, more = rows[:limit], len(rows) > limit and not view.single_page
        if more and _as_datetime(rows[limit][1]) == _as_datetime(page[-1][1]):
            # The page ends inside a run of items with the same timestamp. A cursor on the
            # timestamp alone would skip the rest of the run, so the page takes the whole run.
            boundary = page[-1][1]
            tie = session.exec(paged.where(sort_key == boundary).order_by(Item.id.desc())).all()
            page = [r for r in page if r[1] != boundary] + list(tie)
        items = infer_kinds(radar_items(session, [r[0] for r in page]))
    next_before = _as_datetime(page[-1][1]).isoformat() if more and page else None
    return {"items": items, "next_before": next_before, "total": total}


# --- detail --------------------------------------------------------------------------------


def _related(request: Request, session: Session, item_id: int) -> list[dict]:
    """Embedding neighbours that have been assessed and are not tier "out"."""
    state = getattr(request.app.state, "service_state", None)
    if state is None:
        return []
    try:
        neighbours = [i for i, _ in state.ensure_index().similar(item_id, _RELATED_CANDIDATES)]
    except Exception:  # noqa: BLE001 -- the embedding index is optional context
        logger.exception("related items unavailable for item %s", item_id)
        return []
    if not neighbours:
        return []
    kept = set(session.exec(
        select(Assessment.item_id).where(Assessment.item_id.in_(neighbours), Assessment.tier != "out")
    ).all())
    own = session.get(Item, item_id)
    candidates = infer_kinds(radar_items(session, [i for i in neighbours if i in kept]))
    return unique_related(candidates, own.url if own else "", own.title if own else "")[:_RELATED_SHOWN]


@router.get("/items/{item_id}", dependencies=[Depends(refuse_cross_site)])
def get_item(request: Request, item_id: int) -> dict:
    """The item with its reader document (built on first open), related items and threads."""
    engine, settings = request.app.state.engine, request.app.state.settings
    with Session(engine) as session:
        summary = _require_item(session, item_id).summary
    try:
        reader = ensure_reader_doc(engine, settings, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="item not found") from exc
    with Session(engine) as session:
        base = infer_kinds(radar_items(session, [item_id]))[0]
        state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
        threads = session.exec(
            select(AssistThread).where(AssistThread.item_id == item_id)
            .order_by(AssistThread.updated_at.desc())
        ).all()
        return {
            **base,
            "summary": summary,
            "user_note": state.user_note if state else None,
            "reader": proxied_reader(
                from_you_store.with_missing_picture_notice(reader, settings.data_dir, item_id),
                settings.privacy_proxy_images),
            "related": _related(request, session, item_id),
            "story_sources": story_sources(session, item_id),
            "threads": [
                {"id": t.id, "title": t.title, "updated_at": t.updated_at.isoformat()}
                for t in threads
            ],
        }


@router.post("/items/{item_id}/reader/refresh")
def refresh_reader(request: Request, item_id: int) -> dict:
    """Rebuild the item's reader document from the live page and return it."""
    engine, settings = request.app.state.engine, request.app.state.settings
    with Session(engine) as session:
        _require_item(session, item_id)
    try:
        reader = ensure_reader_doc(engine, settings, item_id, force=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="item not found") from exc
    return proxied_reader(from_you_store.with_missing_picture_notice(reader, settings.data_dir, item_id),
                          settings.privacy_proxy_images)


# --- PDF -----------------------------------------------------------------------------------


def _pdf_source(session: Session, item: Item) -> str | None:
    """The one PDF address this item may serve: the stored alternate, or the item's own PDF URL."""
    doc = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item.id)).first()
    if doc is not None and doc.kind in ("pdf", "paper") and doc.alt_url:
        return doc.alt_url
    aid = arxiv_id(item.url)
    if aid:
        return pdf_url(aid)
    return item.url if classify_url(item.url) == "pdf" else None


@router.get("/items/{item_id}/pdf", dependencies=[Depends(refuse_cross_site)])
def get_item_pdf(request: Request, item_id: int) -> FileResponse:
    """Serve the item's own PDF inline (one the reader sent in, or downloaded once into the PDF cache)."""
    engine, settings = request.app.state.engine, request.app.state.settings
    with Session(engine) as session:
        item = _require_item(session, item_id)
        source = _pdf_source(session, item)
    # A PDF the reader sent in is kept in its own store and cannot be downloaded again.
    owned = from_you_store.find(settings.data_dir, item_id)
    if owned is not None and owned[1] == "application/pdf":
        return FileResponse(owned[0], media_type="application/pdf", headers={"Content-Disposition": "inline"})
    if not source or not is_public_http_url(source):
        raise HTTPException(status_code=404, detail="this item has no PDF")
    try:
        path = ensure_pdf(settings.data_dir, item_id, source)
    except PdfError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


# --- reader actions ------------------------------------------------------------------------


@router.post("/items/{item_id}/signal")
def post_signal(request: Request, item_id: int, body: SignalBody) -> dict:
    """Record that the reader opened the item, spent time on it, or expanded a section."""
    seconds = 0
    if body.kind == "dwell":
        try:
            seconds = int(body.value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="dwell needs integer seconds") from exc
        if seconds < 0:
            raise HTTPException(status_code=422, detail="dwell seconds cannot be negative")
        seconds = min(seconds, MAX_DWELL_SECONDS)
    with Session(request.app.state.engine) as session:
        _require_item(session, item_id)
        state = _state_row(session, item_id)
        if body.kind == "open":
            state.opened_at = utcnow()
            state.open_count += 1
        elif body.kind == "dwell":
            state.read_seconds += seconds
        state.updated_at = utcnow()
        session.add(Signal(item_id=item_id, kind=body.kind,
                           value=str(seconds) if body.kind == "dwell" else (
                               None if body.value is None else str(body.value))))
        session.commit()
        return {"ok": True, "state": _state_dict(session, item_id)}


@router.post("/items/{item_id}/save")
def save_item(request: Request, item_id: int) -> dict:
    """Add the item to the Saved list."""
    return _set_saved(request, item_id, saved=True)


@router.delete("/items/{item_id}/save")
def unsave_item(request: Request, item_id: int) -> dict:
    """Remove the item from the Saved list."""
    return _set_saved(request, item_id, saved=False)


def _set_saved(request: Request, item_id: int, *, saved: bool) -> dict:
    """Set or clear the saved flag and log the matching signal."""
    with Session(request.app.state.engine) as session:
        _require_item(session, item_id)
        state = _state_row(session, item_id)
        state.saved_at = (state.saved_at or utcnow()) if saved else None
        state.updated_at = utcnow()
        session.add(Signal(item_id=item_id, kind="save" if saved else "unsave"))
        session.commit()
        return {"saved": saved, "state": _state_dict(session, item_id)}


@router.post("/items/{item_id}/vote")
def vote_item(request: Request, item_id: int, body: VoteBody) -> dict:
    """Record a more/less-like-this vote (null clears it)."""
    with Session(request.app.state.engine) as session:
        _require_item(session, item_id)
        state = _state_row(session, item_id)
        state.vote = body.vote
        state.updated_at = utcnow()
        session.add(Signal(item_id=item_id, kind="vote", value=body.vote or "none"))
        session.commit()
        return {"vote": body.vote, "state": _state_dict(session, item_id)}
