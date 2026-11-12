"""Hand an item to the reader's own Claude Code, and keep the reader's project directory.

Endpoints (all under /api/radar):
  POST /items/{id}/claude/preview  {intent, project?, custom?, as_kind?} -> the exact request
       text, the vault folder the session opens in, whether it can be opened now and why not,
       and a project hint when the reader's own note names a project
  POST /items/{id}/claude/open     same body -> opens Claude Code in the vault with the request
       typed in (502 with the text to copy when the application cannot be opened)
  GET  /projects                   -> {"projects": [{"name", "description", "in_vault"}]}
  PUT  /projects                   {"projects": [{"name", "description"}]} -> the same shape
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from spyglass_service.claude_link import HandoffStore
from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.radar.claude_bridge import (
    BridgeError,
    OpenFailed,
    open_request,
    preview_request,
)
from spyglass_service.radar.projects import project_directory, save_project_directory
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)
router = APIRouter()
# Used only when the service state has no hand-off store (never in the running service).
_FALLBACK_HANDOFFS = HandoffStore()


class BridgeBody(BaseModel):
    """What the reader wants Claude Code to do with the item."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["file", "discuss", "custom"]
    # Bounded loosely here; the request builder cuts each to its own, smaller limit.
    project: str | None = Field(default=None, max_length=400)
    custom: str | None = Field(default=None, max_length=4000)
    as_kind: Literal["resource", "to explore", "learning", "feature idea"] | None = None


class ProjectEntry(BaseModel):
    """One project and the reader's one-line description of it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=400)
    description: str = Field(default="", max_length=2000)


class ProjectsBody(BaseModel):
    """The whole project directory, as the reader edited it."""

    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectEntry] = Field(max_length=500)


def _fields(body: BridgeBody) -> dict:
    """The body as keyword arguments for the request builder."""
    return {"intent": body.intent, "project": body.project, "custom": body.custom,
            "as_kind": body.as_kind}


@router.post("/items/{item_id}/claude/preview",
             dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def preview(item_id: int, body: BridgeBody, request: Request) -> dict:
    """Exactly what would be sent to Claude Code, and whether it can be opened now."""
    state = request.app.state
    with Session(state.engine) as session:
        try:
            return preview_request(session, state.settings, item_id, **_fields(body),
                                   can_open=getattr(state, "link_opener", None) is not None)
        except BridgeError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("/items/{item_id}/claude/open", response_model=None,
             dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def open_in_claude(item_id: int, body: BridgeBody, request: Request) -> dict | JSONResponse:
    """Open Claude Code in the vault with the request typed in; nothing is filed here."""
    state = request.app.state
    handoffs = getattr(getattr(state, "service_state", None), "handoffs", None)
    if handoffs is None:
        logger.warning("no hand-off store on the service state; long requests cannot be fetched")
        handoffs = _FALLBACK_HANDOFFS
    with Session(state.engine) as session:
        try:
            return open_request(session, state.settings, item_id, **_fields(body),
                                opener=getattr(state, "link_opener", None), handoffs=handoffs)
        except BridgeError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from exc
        except OpenFailed as exc:
            return JSONResponse(status_code=502, content={
                "error": "claude_desktop_unavailable", "text": exc.text})


@router.get("/projects", dependencies=[Depends(refuse_cross_site)])
def get_projects(request: Request) -> dict:
    """The vault's project names merged with the reader's descriptions."""
    state = request.app.state
    with Session(state.engine) as session:
        return {"projects": project_directory(session, state.settings)}


@router.put("/projects", dependencies=[Depends(refuse_cross_site), Depends(require_json)])
def put_projects(body: ProjectsBody, request: Request) -> dict:
    """Replace the reader's project descriptions; returns the merged directory."""
    state = request.app.state
    with Session(state.engine) as session:
        try:
            save_project_directory(session, [e.model_dump() for e in body.projects])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"projects": project_directory(session, state.settings)}
