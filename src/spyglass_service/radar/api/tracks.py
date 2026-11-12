"""Tracks API: suggest what to follow from an item or an address, and manage followed subjects.

Endpoints (all under /api/radar): POST /items/{id}/track/suggest, POST /track/suggest,
GET /tracks, POST /tracks, PATCH /tracks/{id}, DELETE /tracks/{id}. Handlers are plain
functions so FastAPI runs them in its worker threadpool: the model call, the reader build and
the first news search take many seconds and must not block the event loop.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar.brief.llm import make_llm
from spyglass_service.radar.capture import CaptureError, capture_url
from spyglass_service.radar.reader.build import ensure_reader_doc
from spyglass_service.radar.serialize import radar_items
from spyglass_service.radar.track_suggest import similar_now, suggest
from spyglass_service.radar.tracks import (
    TrackConflict, TrackError, TrackNotFound, create_track, delete_track, get_track,
    list_tracks, recent_item_ids, run_track_now, update_track, with_section_label,
)

logger = logging.getLogger(__name__)
router = APIRouter()

Kind = Literal["topic", "organisation", "person", "product"]
# Wide input caps; the exact limits (and readable messages) come from the tracks module.
_WIDE = 2000
RECENT_SHOWN = 3


class UrlBody(BaseModel):
    """An address to read and suggest subjects from."""

    url: str = Field(min_length=1, max_length=_WIDE)


class TrackCreate(BaseModel):
    """A subject to follow."""

    label: str = Field(max_length=_WIDE)
    query: str = Field(max_length=_WIDE)
    section: str = Field(max_length=100)
    kind: Kind
    from_item_id: int | None = None


class TrackPatch(BaseModel):
    """Fields of a track that may change; send only those that do."""

    label: str | None = Field(default=None, max_length=_WIDE)
    query: str | None = Field(default=None, max_length=_WIDE)
    section: str | None = Field(default=None, max_length=100)
    active: bool | None = None


def _fail(exc: Exception) -> HTTPException:
    """The HTTP error for a tracks exception: 404, 409 or 422 with the readable message."""
    if isinstance(exc, TrackNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TrackConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _suggestions_payload(request: Request, item_id: int) -> dict:
    """Suggestions and similar items for a stored item (404 when it does not exist)."""
    engine = request.app.state.engine
    settings = request.app.state.settings
    try:
        suggestions, mode = suggest(engine, item_id, make_llm(settings))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="item not found") from exc
    state = getattr(request.app.state, "service_state", None)
    similar: list[dict] = []
    if state is not None:
        try:
            similar = similar_now(engine, state.ensure_index(), item_id)
        except Exception:  # noqa: BLE001 -- similar items are optional context
            logger.warning("similar items unavailable for item %s", item_id, exc_info=True)
    return {"suggestions": suggestions, "similar": similar, "mode": mode}


@router.post("/items/{item_id}/track/suggest")
def suggest_for_item(item_id: int, request: Request) -> dict:
    """Things the reader could follow after this item, and existing items like it."""
    return _suggestions_payload(request, item_id)


@router.post("/track/suggest")
def suggest_for_url(body: UrlBody, request: Request) -> dict:
    """Capture an address as a from-you item, read it, then suggest as for any item."""
    engine = request.app.state.engine
    settings = request.app.state.settings
    try:
        item_id = capture_url(engine, settings, body.url.strip(), via="manual")
    except CaptureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        ensure_reader_doc(engine, settings, item_id)
    except Exception:  # noqa: BLE001 -- suggestions can still be made from the title alone
        logger.warning("reader build failed for captured item %s", item_id, exc_info=True)
    payload = _suggestions_payload(request, item_id)
    with Session(engine) as session:
        items = radar_items(session, [item_id])
    return {**payload, "item": items[0] if items else None}


def _present(session: Session, track: dict) -> dict:
    """A track with its section label and its newest items."""
    ids = recent_item_ids(session, track["query"], RECENT_SHOWN)
    return {**with_section_label(session, track), "recent": radar_items(session, ids)}


@router.get("/tracks")
def get_tracks(request: Request) -> dict:
    """Every followed subject, newest first, each with up to three recent items."""
    engine = request.app.state.engine
    tracks = list_tracks(engine)
    with Session(engine) as session:
        return {"tracks": [_present(session, t) for t in tracks]}


@router.post("/tracks", status_code=201)
def post_track(body: TrackCreate, request: Request) -> dict:
    """Follow a subject: store it, add it to the profile topics and search for it once now."""
    engine = request.app.state.engine
    settings = request.app.state.settings
    if body.from_item_id is not None:
        with Session(engine) as session:
            if session.get(Item, body.from_item_id) is None:
                raise HTTPException(status_code=422, detail="from_item_id is not a known item")
    try:
        track = create_track(engine, label=body.label, query=body.query, section=body.section,
                             kind=body.kind, from_item_id=body.from_item_id)
    except TrackError as exc:
        raise _fail(exc) from exc
    new_items = run_track_now(engine, settings, track)
    with Session(engine) as session:
        return {**with_section_label(session, get_track(engine, track["id"])),
                "new_items": new_items}


@router.patch("/tracks/{track_id}")
def patch_track(track_id: int, body: TrackPatch, request: Request) -> dict:
    """Change a track's label, query or section, or pause (active false) or resume it."""
    engine = request.app.state.engine
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="nothing to change")
    try:
        track = update_track(engine, track_id, changes)
    except (TrackError, TrackNotFound) as exc:
        raise _fail(exc) from exc
    with Session(engine) as session:
        return _present(session, track)


@router.delete("/tracks/{track_id}")
def remove_track(track_id: int, request: Request) -> dict:
    """Stop following a subject; the profile topic it added goes with it."""
    try:
        delete_track(request.app.state.engine, track_id)
    except TrackNotFound as exc:
        raise _fail(exc) from exc
    return {"deleted": track_id}
