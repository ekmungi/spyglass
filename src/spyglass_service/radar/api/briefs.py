"""Brief endpoints: the latest brief, one day's brief, and "compose now"."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from spyglass_service.radar.brief.compose import compose_brief, local_today
from spyglass_service.radar.brief.document import refresh_states
from spyglass_service.radar.filing_summary import filing_summary
from spyglass_service.radar.models import RadarBrief, loads, utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


class GenerateBody(BaseModel):
    """Body of POST /briefs/generate: the local day to compose (YYYY-MM-DD), or null for today."""

    day: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


# How many days before today a brief the reader never opened is still pointed out.
UNOPENED_LOOKBACK_DAYS = 7


def _unopened_days(rows: list[RadarBrief], today: str) -> list[str]:
    """Days of the stored briefs from the last week, before today, that were never opened.

    `rows` are newest first, so the result is too.
    """
    oldest = (date.fromisoformat(today) - timedelta(days=UNOPENED_LOOKBACK_DAYS)).isoformat()
    return [r.day for r in rows if oldest <= r.day < today and r.opened_at is None]


def _doc(row: RadarBrief, session: Session) -> dict:
    """A stored brief's document with every story's state re-read from the database."""
    return refresh_states(session, loads(row.doc, {}) or {})


@router.get("/today")
def get_today(request: Request) -> dict:
    """The latest brief, the days that have one (newest first) and whether today's exists.

    `unopened_days` lists the briefs of the last week, today's excluded, that were never opened.
    """
    engine, settings = request.app.state.engine, request.app.state.settings
    today = local_today(settings).isoformat()
    with Session(engine) as session:
        # A brief stored for a later day (older versions allowed it) must never become "today".
        rows = session.exec(
            select(RadarBrief).where(RadarBrief.day <= today).order_by(RadarBrief.day.desc())
        ).all()
        latest = rows[0] if rows else None
        brief = None
        if latest is not None:
            if latest.opened_at is None:
                latest.opened_at = utcnow()
                session.add(latest)
                session.commit()
            brief = _doc(latest, session)
        return {
            "brief": brief,
            "days": [r.day for r in rows],
            "unopened_days": _unopened_days(rows, today),
            "status": {
                "today": today,
                "has_today": any(r.day == today for r in rows),
                "latest_day": latest.day if latest else None,
                "generated_at": brief["generated_at"] if brief else None,
            },
            # One line on background filing for under the masthead, or null (filing_summary.py).
            "filing": filing_summary(engine, settings),
        }


@router.get("/briefs/{day}")
def get_brief(day: str, request: Request) -> dict:
    """One day's brief document; 404 when that day has none."""
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must look like 2026-11-12") from None
    with Session(request.app.state.engine) as session:
        row = session.exec(select(RadarBrief).where(RadarBrief.day == day)).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No brief for {day}")
        if row.opened_at is None:
            row.opened_at = utcnow()
            session.add(row)
            session.commit()
        return _doc(row, session)


@router.post("/briefs/generate")
async def generate_brief(body: GenerateBody, request: Request) -> dict:
    """Compose the brief now (replacing that day's brief) and return it."""
    engine, settings = request.app.state.engine, request.app.state.settings
    try:
        index = request.app.state.service_state.ensure_index()
    except Exception:
        logger.exception("Embedding index unavailable; composing without near-duplicate merging")
        index = None
    try:
        return await run_in_threadpool(compose_brief, engine, settings, index, body.day)
    except ValueError as exc:  # an impossible date such as 2026-02-31, or a future day
        raise HTTPException(status_code=422, detail=str(exc)) from exc

