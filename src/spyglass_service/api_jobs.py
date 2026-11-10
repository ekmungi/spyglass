"""Dashboard endpoints for background jobs and detailed notes."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from spyglass_service import claude_jobs as jobs
from spyglass_service.detail_notes import (
    NoteNotRemovable,
    delete_detail_note,
    in_spyglass_folder,
    relocate_note,
    vault_relative,
)
from spyglass_service.models import Card
from spyglass_service.request_guards import require_json

router = APIRouter(prefix="/api")


class JobPayload(BaseModel):
    kind: Literal["prepare-detail", "file-note"]
    card_id: int


def _note_info(settings, engine, card: Card) -> dict:
    """The card's note as the reader shows it: where it is, and whether it is still unfiled.
    A note moved without Spyglass knowing is looked for by its spyglass_item property."""
    path = card.briefing_path
    if path and not Path(path).is_file() and relocate_note(settings, engine, card.id):
        with Session(engine) as session:
            path = session.get(Card, card.id).briefing_path
    exists = bool(path) and Path(path).is_file()
    return {
        "path": vault_relative(settings, path) if exists else None,
        "unfiled": exists and in_spyglass_folder(settings, path),
    }


@router.post("/jobs", dependencies=[Depends(require_json)])
def start_job(request: Request, body: JobPayload) -> dict:
    """Queue Prepare detail or File it for one card; an identical job already queued or running
    is returned instead of a second one."""
    settings = request.app.state.settings
    engine = request.app.state.engine
    if settings.vault_path is None:
        raise HTTPException(status_code=409, detail="Set the vault folder in Settings first.")
    with Session(engine) as session:
        card = session.get(Card, body.card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="No such item.")
    note = _note_info(settings, engine, card)
    if body.kind == jobs.PREPARE and note["path"]:
        raise HTTPException(status_code=409, detail="This item already has a note.")
    if body.kind == jobs.FILE and not note["path"]:
        raise HTTPException(status_code=409, detail="This item has no note to file.")
    if body.kind == jobs.FILE and not note["unfiled"]:
        raise HTTPException(status_code=409,
                            detail="This note is already filed. Use Move to change where it is.")
    job, created = jobs.enqueue(engine, body.kind, body.card_id)
    request.app.state.claude_worker.wake()
    return {"job": job, "created": created}


@router.get("/cards/{card_id}/jobs")
def card_jobs(request: Request, card_id: int) -> dict:
    """A card's latest jobs, newest first, and its note."""
    settings = request.app.state.settings
    engine = request.app.state.engine
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="No such item.")
    paused = request.app.state.claude_worker.paused_until
    return {"jobs": jobs.jobs_for_card(engine, card_id), "note": _note_info(settings, engine, card),
            "paused_until": paused.isoformat() if paused else None}


@router.get("/jobs/active")
def active(request: Request) -> list[dict]:
    """Every queued or running job."""
    return jobs.active_jobs(request.app.state.engine)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_json)])
def cancel_job(request: Request, job_id: int) -> dict:
    job = jobs.cancel(request.app.state.engine, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    return job


@router.post("/cards/{card_id}/detail-note/delete", dependencies=[Depends(require_json)])
def delete_note(request: Request, card_id: int) -> dict:
    """Move an unfiled detailed note to the vault's .trash; counts as a thumbs down. Refused
    while a job for the item is queued or running."""
    engine = request.app.state.engine
    if any(job["card_id"] == card_id for job in jobs.active_jobs(engine)):
        raise HTTPException(status_code=409,
                            detail="A background job is working on this note. Wait or cancel it.")
    try:
        trashed = delete_detail_note(request.app.state.settings, request.app.state.engine,
                                     card_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="No such item.") from exc
    except NoteNotRemovable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"trashed": trashed}
