"""Profile endpoints: read the reader's profile with its derived examples, and replace it.

GET /profile returns {"profile": doc, "examples": {"liked": [...], "disliked": [...]}}; the
examples are exactly the titles the judging model is sent (none when the reader switched them off).
PUT /profile validates the body, bumps `version` and returns the same shape.
"""

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import Session

from spyglass_service.radar.profile import (
    ProfileDoc,
    ProfileError,
    get_profile,
    refresh_examples,
    save_profile,
)

router = APIRouter()


def _settings(request: Request) -> object | None:
    """The service's settings (the example switch lives there); None lets the profile load them."""
    return getattr(request.app.state, "settings", None)


@router.get("/profile")
def read_profile(request: Request) -> dict:
    """The stored profile (or the default) and the examples derived from the reader's history."""
    with Session(request.app.state.engine) as session:
        return {"profile": get_profile(session),
                "examples": refresh_examples(session, settings=_settings(request))}


@router.put("/profile")
def write_profile(body: ProfileDoc, request: Request) -> dict:
    """Replace the profile; the stored version becomes the previous version plus one."""
    with Session(request.app.state.engine) as session:
        try:
            saved = save_profile(session, body.model_dump())
        except ProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"profile": saved, "examples": refresh_examples(session, settings=_settings(request))}
