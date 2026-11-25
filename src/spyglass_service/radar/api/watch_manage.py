"""Watch endpoints for whole groups and for the AI review of the register.

PATCH /watch/groups, POST /watch/groups/restore, POST /watch/suggestions/status, POST /watch/review
and POST /watch/review/apply.
They are included by `api/watch.py` ahead of its `/watch/{id}` routes so "groups" is never read
as an id. Each change answers with the fresh register (the `GET /watch` payload).
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from spyglass_service.radar.models import WatchEntity
from spyglass_service.radar.watch import groups, registry, review, review_apply

logger = logging.getLogger(__name__)
router = APIRouter()

Kind = Literal["company", "lab", "regulator", "person", "publication"]
Status = Literal["active", "suggested", "muted", "rejected"]


class GroupBody(BaseModel):
    """Body of PATCH /watch/groups: one action on every entry of a group ("up" and "down" move the group in the page order).

    `ids`, only with "pause" or "resume", limits the action to those entries of the group.
    """

    category: str = Field(min_length=1, max_length=groups.MAX_CATEGORY)
    action: Literal["pause", "resume", "rename", "move", "remove", "up", "down"]
    to: str | None = Field(default=None, max_length=200)
    ids: list[int] | None = Field(default=None, max_length=500)


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
    # Higher than the ten a reader may type: each suggestion refresh can add another spelling.
    aliases: list[str] = Field(default_factory=list, max_length=50)
    query: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    status: Status = "active"
    section: str = Field(default="", max_length=120)
    count: int = Field(default=0, ge=0)
    why: str | None = Field(default=None, max_length=300)
    added_via: str = Field(default="user", max_length=30)
    last_hit_at: str | None = Field(default=None, max_length=40)
    links: list[LinkBody] = Field(default_factory=list, max_length=5000)


class RestoreBody(BaseModel):
    """Body of POST /watch/groups/restore."""

    entries: list[RestoreEntry] = Field(max_length=200)


class SuggestionsBody(BaseModel):
    """Body of POST /watch/suggestions/status: undecided suggestions to hide ("rejected") or take back ("suggested")."""

    ids: list[int] = Field(max_length=500)
    status: Literal["rejected", "suggested"]


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
    """Pause, resume, rename, move or remove every entry of a group, or move the group up or down the page; answers the fresh register.

    The answer also carries `removed`, the removed entries (empty unless the action is "remove"),
    which `POST /watch/groups/restore` takes back for Undo. With `ids` (pause or resume only) just
    those entries of the group change, and the answer also carries `changed`, the ids that did.
    """
    changed: list[int] | None = None
    with Session(request.app.state.engine) as session:
        try:
            if body.ids is None:
                removed = groups.apply_group_action(session, body.category, body.action, to=body.to)
            else:
                removed, changed = [], groups.switch_names(session, body.category, body.action, body.ids)
        except groups.GroupNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except groups.GroupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    extra = {} if changed is None else {"changed": changed}
    return {**_register(request), "removed": removed, **extra}


@router.post("/watch/groups/restore")
def restore_group(body: RestoreBody, request: Request) -> dict:
    """Bring back removed entries (Undo for a removed group); answers the fresh register."""
    entries = [e.model_dump() for e in body.entries]
    with Session(request.app.state.engine) as session:
        restored = groups.restore_entries(session, entries)
    return {**_register(request), "restored": restored}


@router.post("/watch/suggestions/status")
def set_suggestions_status(body: SuggestionsBody, request: Request) -> dict:
    """Hide many suggestions at once ("rejected"), or take them back ("suggested"); answers the fresh register.

    Only names that are currently a suggestion or rejected are touched, so a watched or paused
    name can never be changed through this route; such ids, and unknown ids, are ignored. A
    suggestion the page does not show (`registry.shown_suggestion`: one no cycle has placed yet)
    is ignored too, so it cannot be hidden unseen. The answer also carries `changed`, the ids
    whose status actually changed, in the order sent.
    """
    wanted = list(dict.fromkeys(body.ids))
    with Session(request.app.state.engine) as session:
        rows = session.exec(
            select(WatchEntity).where(WatchEntity.id.in_(wanted), WatchEntity.status.in_(("suggested", "rejected")))
        ).all()
        by_id = {row.id: row for row in rows if row.status == "rejected" or registry.shown_suggestion(row)}
        changed = [i for i in wanted if i in by_id and by_id[i].status != body.status]
        for i in changed:
            by_id[i].status = body.status
            session.add(by_id[i])
        session.commit()
    return {**_register(request), "changed": changed}


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
