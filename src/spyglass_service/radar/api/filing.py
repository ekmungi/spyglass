"""The "To file" queue API: mark items for filing, and open one session that files them all.

Endpoints (all under /api/radar):
  POST   /items/{id}/file   {kind?, project?, note?} -> {item_id, filing: "waiting", count}
  DELETE /items/{id}/file   -> {item_id, filing: null, count}
  GET    /filing            -> {count, waiting: [{item, kind, project, note, requested_at}],
                                status, questions, plan, recent} (the background run's side, see
                                `radar/filing_view.py`)
  POST   /filing/preview    -> the batch request text, the vault and whether it can open now
  POST   /filing/open       -> opens ONE Claude Code session in the vault (502 with the text to
                              copy when the application cannot be opened)
Answers, plan approval and opening a filed note are in `filing_answers.py`, included here.
Nothing here writes into the vault; filing happens in a Claude Code session.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from spyglass_service.claude_link import HandoffStore
from spyglass_service.models import Item
from spyglass_service.radar import filing_queue
from spyglass_service.radar.api import filing_answers
from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.radar.claude_bridge import BridgeError, OpenFailed
from spyglass_service.radar.filing_config import NOT_CONFIGURED, filing_configured
from spyglass_service.radar.filing_request import open_batch, preview_batch
from spyglass_service.radar.filing_view import plan_view, questions_view, recent_view, status_view
from spyglass_service.radar.serialize import radar_items
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(filing_answers.router)
# Used only when the service state has no hand-off store (never in the running service).
_FALLBACK_HANDOFFS = HandoffStore()


class FileBody(BaseModel):
    """The reader's choices when queuing an item; all optional."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource", "to explore", "learning", "feature idea"] | None = None
    # Bounded loosely here; the queue cuts each to its own, smaller limit.
    project: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=2000)


@router.post("/items/{item_id}/file",
             dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def queue_item(item_id: int, body: FileBody, request: Request) -> dict:
    """Put the item in the "To file" queue (or change its row); nothing is opened or written.

    409 when filing into a notes vault is not set up on this Spyglass."""
    state = request.app.state
    if not filing_configured(state.settings):
        raise HTTPException(status_code=409, detail=NOT_CONFIGURED)
    with Session(state.engine) as session:
        if session.get(Item, item_id) is None:
            raise HTTPException(status_code=404, detail="item not found")
        found = radar_items(session, [item_id])
        if found and found[0].get("filed"):
            raise HTTPException(status_code=409, detail="This item is already filed.")
        try:
            project = filing_queue.check_project(session, state.settings, body.project)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    filing_queue.enqueue(state.engine, item_id, kind=body.kind or filing_queue.DEFAULT_KIND,
                         project=project, note=body.note)
    return {"item_id": item_id, "filing": "waiting", "count": filing_queue.count(state.engine)}


@router.delete("/items/{item_id}/file", dependencies=[Depends(refuse_cross_site)])
def unqueue_item(item_id: int, request: Request) -> dict:
    """Take the item out of the queue; fine when it was not queued."""
    engine = request.app.state.engine
    filing_queue.dequeue(engine, item_id)
    return {"item_id": item_id, "filing": None, "count": filing_queue.count(engine)}


@router.get("/filing", dependencies=[Depends(refuse_cross_site)])
def get_queue(request: Request) -> dict:
    """Every waiting item (oldest first) with the reader's choices, plus the background run's
    status, open questions, plan rows and the notes filed in the last 14 days."""
    engine, settings = request.app.state.engine, request.app.state.settings
    entries = filing_queue.waiting(engine)
    with Session(engine) as session:
        items = {i["id"]: i for i in radar_items(session, [e.item_id for e in entries])}
    rows = [{"item": items[e.item_id], "kind": e.kind, "project": e.project, "note": e.note,
             "requested_at": e.requested_at.isoformat()} for e in entries if e.item_id in items]
    return {"count": len(rows), "waiting": rows, "status": status_view(engine, settings),
            "questions": questions_view(engine), "plan": plan_view(engine),
            "recent": recent_view(engine)}


@router.post("/filing/preview", dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def preview(request: Request) -> dict:
    """Exactly what would be sent to Claude Code for the whole queue; nothing is opened.

    {"available": false, "detail"} when filing is not set up on this Spyglass."""
    state = request.app.state
    if not filing_configured(state.settings):
        return {"available": False, "detail": NOT_CONFIGURED}
    try:
        return preview_batch(state.engine, state.settings,
                             can_open=getattr(state, "link_opener", None) is not None)
    except BridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("/filing/open", response_model=None,
             dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def open_queue(request: Request) -> dict | JSONResponse:
    """Open ONE Claude Code session in the vault to file the whole queue.

    {"available": false, "detail"} when filing is not set up on this Spyglass."""
    state = request.app.state
    if not filing_configured(state.settings):
        return {"available": False, "detail": NOT_CONFIGURED}
    handoffs = getattr(getattr(state, "service_state", None), "handoffs", None)
    if handoffs is None:
        logger.warning("no hand-off store on the service state; long requests cannot be fetched")
        handoffs = _FALLBACK_HANDOFFS
    try:
        return open_batch(state.engine, state.settings,
                          opener=getattr(state, "link_opener", None), handoffs=handoffs)
    except BridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except OpenFailed as exc:
        return JSONResponse(status_code=502, content={
            "error": "claude_desktop_unavailable", "text": exc.text})
