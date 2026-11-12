"""Watch endpoints: the register, discovery of new names, manual changes, groups and the AI review."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from spyglass_service.radar.api.watch_manage import router as manage_router
from spyglass_service.radar.watch import registry
from spyglass_service.radar.watch.discover import discover_detailed

logger = logging.getLogger(__name__)

router = APIRouter()
# Group and review routes go first so "/watch/groups" is never read as an entity id.
router.include_router(manage_router)

Kind = Literal["company", "lab", "regulator", "person", "publication"]
Status = Literal["active", "suggested", "muted"]


class DiscoverBody(BaseModel):
    """Body of POST /watch/discover."""

    topic: str = Field(min_length=2, max_length=200)


class NewEntity(BaseModel):
    """Body of POST /watch: a company, lab or regulator to follow."""

    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "company"
    category: str = Field(default="", max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    query: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)


class EntityChanges(BaseModel):
    """Body of PATCH /watch/{id}; only the fields present are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Kind | None = None
    category: str | None = Field(default=None, max_length=60)
    status: Status | None = None
    aliases: list[str] | None = Field(default=None, max_length=10)
    query: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    why: str | None = Field(default=None, max_length=300)


@router.get("/watch")
def get_watch(request: Request) -> dict:
    """The register grouped by category, with recent items per entity, and the suggestions."""
    with Session(request.app.state.engine) as session:
        return registry.grouped(session)


@router.post("/watch/discover")
async def discover_watch(body: DiscoverBody, request: Request) -> dict:
    """Ask the model for organisations for a topic, verify them, and store them as suggested."""
    engine, settings = request.app.state.engine, request.app.state.settings
    try:
        result = await run_in_threadpool(discover_detailed, engine, settings, body.topic.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Watch discovery failed")
        raise HTTPException(status_code=502, detail="The model request failed; try again later") from exc
    return {"suggested": result.accepted, "rejected": len(result.rejected), "already_known": len(result.existing)}


@router.post("/watch", status_code=201)
def add_entity(body: NewEntity, request: Request) -> dict:
    """Follow a new entity (active at once)."""
    with Session(request.app.state.engine) as session:
        try:
            entity = registry.create_entity(
                session, body.name, kind=body.kind, category=body.category, aliases=body.aliases,
                query=body.query, website=body.website,
            )
        except registry.DuplicateEntity as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return registry.entity_dict(entity)


@router.patch("/watch/{entity_id}")
def change_entity(entity_id: int, body: EntityChanges, request: Request) -> dict:
    """Edit an entity, or accept (status "active") or mute it."""
    with Session(request.app.state.engine) as session:
        try:
            entity = registry.update_entity(session, entity_id, body.model_dump(exclude_unset=True))
        except registry.DuplicateEntity as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if entity is None:
            raise HTTPException(status_code=404, detail="No such entity")
        return registry.entity_dict(entity)


@router.delete("/watch/{entity_id}")
def remove_entity(entity_id: int, request: Request) -> dict:
    """Stop following an entity and forget its links."""
    with Session(request.app.state.engine) as session:
        if not registry.delete_entity(session, entity_id):
            raise HTTPException(status_code=404, detail="No such entity")
    return {"deleted": entity_id}
