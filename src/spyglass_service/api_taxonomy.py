"""User taxonomy REST: managed categories + per-card relevance/category override."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from spyglass_service.categories import (
    add_category,
    delete_category,
    list_categories,
    rename_category,
    set_user_category,
)
from spyglass_service.recategorize import accept_candidate, latest_candidates
from spyglass_service.relevance import set_user_relevance

router = APIRouter(prefix="/api")


class CategoryCreate(BaseModel):
    """Body for creating a new (empty) category."""

    name: str


class CategoryPatch(BaseModel):
    """Body for recategorizing a card."""

    category: str


class RelevancePatch(BaseModel):
    """Body for setting/clearing a card's manual relevance override.

    A validated level sets the override; null clears it (revert to the AI baseline).
    An out-of-range value is a 422 validation error, never a silent write.
    """

    relevance: Literal["high", "medium", "low", "out"] | None = None


class CandidateAccept(BaseModel):
    """Body for accepting a Recategorize candidate: the new category name + its cluster's cards."""

    name: str
    card_ids: list[int]


@router.get("/categories")
def get_categories(request: Request) -> list[dict]:
    """All managed categories with card counts, empty ones included."""
    return list_categories(request.app.state.engine)


@router.post("/categories", status_code=201)
def create_category(request: Request, body: CategoryCreate) -> dict:
    """Create an empty category that persists even with zero cards."""
    add_category(request.app.state.engine, body.name)
    return {"name": body.name}


@router.patch("/categories/{name}")
def patch_category(request: Request, name: str, body: CategoryCreate) -> dict:
    """Rename a category across the managed set and every card (override state is untouched)."""
    if not rename_category(request.app.state.engine, name, body.name):
        raise HTTPException(status_code=404, detail="category not found")
    return {"name": body.name}


@router.delete("/categories/{name}")
def remove_category(request: Request, name: str) -> dict:
    """Remove a managed category; its cards re-bucket to Unsorted."""
    if not delete_category(request.app.state.engine, name):
        raise HTTPException(status_code=404, detail="category not found")
    return {"deleted": name}


@router.get("/recategorize")
def get_recategorize(request: Request) -> dict:
    """Latest Recategorize run: status ('none'|'running'|'ok'|'error') + candidate categories.

    Polled by the Settings review UI after a kick; returns the parsed candidate list from the
    most recent run so proposed new categories can be accepted or discarded.
    """
    return latest_candidates(request.app.state.engine)


@router.post("/recategorize/accept")
def post_recategorize_accept(request: Request, body: CandidateAccept) -> dict:
    """Accept one candidate: register the new category and file its cluster's cards into it.

    A new category enters the managed set only through this accept (or a manual +), never
    silently from the pass. A blank name is rejected -- never register an empty bucket.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="category name is required")
    return accept_candidate(request.app.state.engine, name, body.card_ids)


@router.patch("/cards/{card_id}/category")
def patch_card_category(request: Request, card_id: int, body: CategoryPatch) -> dict:
    """Recategorize one card; override flags only on a net change vs the AI value."""
    result = set_user_category(request.app.state.engine, card_id, body.category)
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return result


@router.patch("/cards/{card_id}/relevance")
def patch_card_relevance(request: Request, card_id: int, body: RelevancePatch) -> dict:
    """Set or clear one card's manual relevance override.

    A level marks relevance_override (unless it equals the AI value -- the net-change
    rule); null reverts to the AI baseline. 404 if the card is unknown.
    """
    result = set_user_relevance(request.app.state.engine, card_id, body.relevance)
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return result
