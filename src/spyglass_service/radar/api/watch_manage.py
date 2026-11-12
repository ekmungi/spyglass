"""Watch endpoints for whole groups and for the AI review of the register.

PATCH /watch/groups, POST /watch/groups/restore, POST /watch/review and POST /watch/review/apply.
They are included by `api/watch.py` ahead of its `/watch/{id}` routes so "groups" is never read
as an id. Each change answers with the fresh register (the `GET /watch` payload).
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from spyglass_service.radar.watch import groups, registry, review, review_apply

logger = logging.getLogger(__name__)
router = APIRouter()

Kind = Literal["company", "lab", "regulator", "person", "publication"]
Status = Literal["active", "suggested", "muted"]


class GroupBody(BaseModel):
    """Body of PATCH /watch/groups: one action on every entry of a group."""

    category: str = Field(min_length=1, max_length=groups.MAX_CATEGORY)
    action: Literal["pause", "resume", "rename", "move", "remove"]
    to: str | None = Field(default=None, max_length=200)


class LinkBody(BaseModel):
    """An item link carried with a removed entry so Undo can bring it back."""

    item_id: int
    via: str = Field(default="query", max_length=20)


class RestoreEntry(BaseModel):
    """One removed entry, as PATCH /watch/groups returned it."""

    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "company"
    category: str = Field(default="", max_length=groups.MAX_CATEGORY)
    topic: str | None = Field(default=None, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    query: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    status: Status = "active"
    why: str | None = Field(default=None, max_length=300)
    added_via: str = Field(default="user", max_length=30)
    last_hit_at: str | None = Field(default=None, max_length=40)
    links: list[LinkBody] = Field(default_factory=list, max_length=5000)


class RestoreBody(BaseModel):
    """Body of POST /watch/groups/restore."""

    entries: list[RestoreEntry] = Field(max_length=200)


class AddProposal(BaseModel):
    """An organisation the reader ticked in the review to add."""

    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "company"
    category: str = Field(default="", max_length=groups.MAX_CATEGORY)
    why: str = Field(default="", max_length=300)
    query: str = Field(default="", max_length=200)


class RegroupProposal(BaseModel):
    """One name the reader ticked to move to another group."""

    id: int
    to: str = Field(min_length=1, max_length=200)


class MergeProposal(BaseModel):
    """Two groups the reader ticked to merge: everything in `from` moves into `to`."""

    from_: str = Field(alias="from", min_length=1, max_length=200)
    to: str = Field(min_length=1, max_length=200)


class ApplyBody(BaseModel):
    """Body of POST /watch/review/apply: exactly what the reader ticked."""

    pause: list[int] = Field(default_factory=list, max_length=100)
    remove: list[int] = Field(default_factory=list, max_length=100)
    add: list[AddProposal] = Field(default_factory=list, max_length=50)
    regroup: list[RegroupProposal] = Field(default_factory=list, max_length=100)
    merge_groups: list[MergeProposal] = Field(default_factory=list, max_length=50)


def _register(request: Request) -> dict:
    """The fresh `GET /watch` payload."""
    with Session(request.app.state.engine) as session:
        return registry.grouped(session)


@router.patch("/watch/groups")
def change_group(body: GroupBody, request: Request) -> dict:
    """Pause, resume, rename, move or remove every entry of a group; answers the fresh register.

    The answer also carries `removed`, the removed entries (empty unless the action is "remove"),
    which `POST /watch/groups/restore` takes back for Undo.
    """
    with Session(request.app.state.engine) as session:
        try:
            removed = groups.apply_group_action(session, body.category, body.action, to=body.to)
        except groups.GroupNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except groups.GroupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_register(request), "removed": removed}


@router.post("/watch/groups/restore")
def restore_group(body: RestoreBody, request: Request) -> dict:
    """Bring back removed entries (Undo for a removed group); answers the fresh register."""
    entries = [e.model_dump() for e in body.entries]
    with Session(request.app.state.engine) as session:
        restored = groups.restore_entries(session, entries)
    return {**_register(request), "restored": restored}


@router.post("/watch/review")
async def review_watch(request: Request) -> dict:
    """Review the register and propose changes; nothing is changed.

    Answers `mode` ("ai" or "basic"), `summary`, optionally `note`, and the lists `pause`,
    `remove`, `add`, `regroup` and `merge_groups`. With a model this can take up to a minute.
    """
    engine, settings = request.app.state.engine, request.app.state.settings
    try:
        return await run_in_threadpool(review.review, engine, settings)
    except Exception as exc:
        logger.exception("Watch review failed")
        raise HTTPException(status_code=502, detail="The review could not be completed; try again later") from exc


@router.post("/watch/review/apply")
def apply_review(body: ApplyBody, request: Request) -> dict:
    """Apply exactly the proposals the reader ticked; answers the fresh register.

    The answer also carries `applied` (counts) and `removed` (the removed entries, for Undo).
    """
    selection = {
        "pause": body.pause, "remove": body.remove,
        "add": [a.model_dump() for a in body.add],
        "regroup": [r.model_dump() for r in body.regroup],
        "merge_groups": [{"from": m.from_, "to": m.to} for m in body.merge_groups],
    }
    try:
        result = review_apply.apply_review(request.app.state.engine, selection)
    except groups.GroupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_register(request), **result}
