"""The linked Claude session, seen from the dashboard.

GET /api/link says whether a session is linked, since when and when it last called Spyglass.
POST /api/link/open opens a new Claude desktop session that claims the link with a one-time
code; the items the user points at are recorded first, so "this one" works at once.
POST /api/link/end ends the link. POST /api/link/window-closed is sent by a closing Spyglass
window; when no window checks the link again soon after, the link ends.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spyglass_service.claude_link import card_titles, name_cards, session_link
from spyglass_service.linked_session import link_prompt
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)

router = APIRouter()


class OpenLinkPayload(BaseModel):
    """Optional: the items to point at, and a task for the new session after it links."""

    card_ids: list[int] | None = None
    task: str | None = None


@router.get("/api/link")
def link_status(request: Request) -> dict:
    """Whether a Claude session is linked, since when, last contact, and a code waiting. Only
    Spyglass windows ask, so asking also says a window is open."""
    link = request.app.state.service_state.link
    link.dashboard_seen()
    return link.status()


@router.post("/api/link/end", dependencies=[Depends(require_json)])
def end_link(request: Request) -> dict:
    """End the link: the linked Claude session's next call to Spyglass is refused."""
    link = request.app.state.service_state.link
    link.end()
    return link.status()


@router.post("/api/link/window-closed", status_code=204, dependencies=[Depends(require_json)])
def window_closed(request: Request) -> None:
    """A Spyglass window is closing; the link ends unless a window checks in again soon."""
    request.app.state.service_state.link.window_closed()


@router.post("/api/link/open", response_model=None, dependencies=[Depends(require_json)])
def open_linked_session(request: Request, payload: OpenLinkPayload) -> dict | JSONResponse:
    """Open a new Claude desktop session that becomes the linked one when it claims its code.

    502 with the prompt when the desktop app cannot be opened, so the dashboard can offer to
    copy it instead.
    """
    settings = request.app.state.settings
    state = request.app.state.service_state
    if settings.vault_path is None:
        raise HTTPException(status_code=409, detail="vault_path is not configured")
    if payload.card_ids is not None:
        state.set_selection(payload.card_ids)
    code = state.link.issue_code()
    prompt = name_cards(link_prompt(code, payload.task), card_titles(state.engine, state.selection))
    url = session_link(prompt, settings.vault_path, state.handoffs)
    try:
        request.app.state.link_opener(url)
    except Exception:  # noqa: BLE001 -- any failure to open means "not available"
        logger.warning("Could not open the Claude desktop app", exc_info=True)
        return JSONResponse(
            status_code=502, content={"error": "claude_desktop_unavailable", "prompt": prompt}
        )
    return {"opened": True}
