"""The background run's side of the "To file" API: answers, plan approval, opening filed notes.

Endpoints (all under /api/radar, included by `radar/api/filing.py`):
  POST /filing/answers        {answers: [{question_id, choice}]} -> {answered}; all or nothing
  POST /filing/plan/approve   {approved: [row id], struck: [row id]} -> {approved, struck}
  POST /filing/recent/{id}/open -> opens the item's filed note in Obsidian (404 when not filed,
                                   502 when Obsidian could not be opened)
Nothing here writes into the vault: answers and approvals are stored in Spyglass and the next
background run carries them out. The note to open comes only from the path a filing run recorded
(checked when it was recorded and again when it is opened), never from the request.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from spyglass_service.api_inbox import _open_vault_note
from spyglass_service.radar import filing_plan, filing_questions
from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)
router = APIRouter()
GUARDS = [Depends(refuse_cross_site), Depends(require_json)]


class Answer(BaseModel):
    """One answered line: the question and the chosen option (a project name or "No project")."""

    model_config = ConfigDict(extra="forbid")

    question_id: int
    choice: str = Field(min_length=1, max_length=100)


class AnswersBody(BaseModel):
    """Every answered line of one submit."""

    model_config = ConfigDict(extra="forbid")

    answers: list[Answer] = Field(min_length=1, max_length=200)


class ApproveBody(BaseModel):
    """The plan rows the reader approved and struck in one press of Approve."""

    model_config = ConfigDict(extra="forbid")

    approved: list[int] = Field(default_factory=list, max_length=200)
    struck: list[int] = Field(default_factory=list, max_length=200)


@router.post("/filing/answers", dependencies=GUARDS)
def submit_answers(body: AnswersBody, request: Request) -> dict:
    """Store all answers at once; 422 (and nothing stored) when one is not valid."""
    try:
        return filing_questions.submit_answers(
            request.app.state.engine, [(a.question_id, a.choice) for a in body.answers])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/filing/plan/approve", dependencies=GUARDS)
def approve_plan(body: ApproveBody, request: Request) -> dict:
    """Approve and strike plan rows at once; 422 (and nothing changed) when a row is not valid."""
    if not body.approved and not body.struck:
        raise HTTPException(status_code=422, detail="Approve or strike at least one row.")
    try:
        return filing_plan.decide(request.app.state.engine, approved=body.approved,
                                  struck=body.struck)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/filing/recent/{item_id}/open", response_model=None, dependencies=GUARDS)
def open_filed_note(item_id: int, request: Request) -> dict | JSONResponse:
    """Open the note a run (or a visible session) recorded for this item, in Obsidian."""
    with Session(request.app.state.engine) as session:
        filed = filing_questions.filed_entry(session, item_id)
    if filed is None:
        raise HTTPException(status_code=404, detail="This item has no filed note.")
    return _open_vault_note(request, str(filed["path"]))
