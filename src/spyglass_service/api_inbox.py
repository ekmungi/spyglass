"""Paper inbox REST API for the Inbox tab.

GET /api/inbox lists the shared papers and the latest run. POST /api/inbox/{card_id}/open-note
opens a paper's vault note, and POST /api/inbox/runs/{run_id}/open-debrief a run's debrief,
in Obsidian (obsidian://open), through the same opener that hands
claude:// links to the operating system. Runs themselves are reported by the Claude session
through the MCP tools (inbox_start ... inbox_finish); the dashboard only starts a session.
"""

from pathlib import Path
from urllib.parse import quote

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from spyglass_service.inbox import inbox_view
from spyglass_service.inbox_debrief import recent_debriefs
from spyglass_service.models import Card, InboxRun

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/inbox")
def get_inbox(request: Request) -> dict:
    """The inbox channel, the latest run, the recent run debriefs and the shared papers."""
    settings = request.app.state.settings
    engine = request.app.state.engine
    view = inbox_view(engine, settings.inbox_channel.strip().lstrip("#"))
    return {**view, "debriefs": recent_debriefs(engine)}


def _open_vault_note(request: Request, note: str) -> dict | JSONResponse:
    """Open a note in Obsidian: 403 outside the vault, 502 when Obsidian could not be opened."""
    vault = request.app.state.settings.vault_path
    if vault is None:
        raise HTTPException(status_code=409, detail="vault_path is not configured")
    path = Path(note)
    path = (path if path.is_absolute() else vault / path).resolve()
    if vault.resolve() not in path.parents:
        raise HTTPException(status_code=403, detail="note outside the vault")
    try:
        request.app.state.link_opener(f"obsidian://open?path={quote(str(path), safe='')}")
    except Exception:  # noqa: BLE001 -- any failure to open means "not available"
        logger.warning("Could not open Obsidian", exc_info=True)
        return JSONResponse(status_code=502, content={"error": "obsidian_unavailable"})
    return {"opened": True}


@router.post("/inbox/{card_id}/open-note", response_model=None)
def open_note(request: Request, card_id: int) -> dict | JSONResponse:
    """Open the paper's vault note (its debrief) in Obsidian. 404 when it has no note yet."""
    with Session(request.app.state.engine) as session:
        card = session.get(Card, card_id)
        note = card.briefing_path if card else None
    if not note:
        raise HTTPException(status_code=404, detail="this paper has no vault note yet")
    return _open_vault_note(request, note)


@router.post("/inbox/runs/{run_id}/open-debrief", response_model=None)
def open_run_debrief(request: Request, run_id: int) -> dict | JSONResponse:
    """Open a run's debrief note in Obsidian. 404 when the run wrote none."""
    with Session(request.app.state.engine) as session:
        run = session.get(InboxRun, run_id)
        note = run.debrief_path if run else None
    if not note:
        raise HTTPException(status_code=404, detail="this run has no debrief")
    return _open_vault_note(request, note)
