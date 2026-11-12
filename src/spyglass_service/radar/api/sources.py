"""Sources API: what is being collected, sending in a link, collecting now, and system status."""

import logging
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from spyglass_service.models import Embedding, Feed, Item, RunLog
from spyglass_service.radar.capture import CaptureError, capture_url
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.serialize import radar_items
from spyglass_service.radar.sources import COLLECTORS, RUN_SOURCES

logger = logging.getLogger(__name__)

router = APIRouter()

# Radar collector key -> label shown on the sources screen.
COLLECTOR_LABELS = {
    "news": "News search", "hn": "Hacker News", "hf_papers": "Community papers",
    "gmail": "Email newsletters and links", "slack": "Slack links",
    "watch": "Watch list sweep", "fda": "FDA device decisions",
}
# The engine's own collectors, whose RunLog rows are named rss and raindrop.
LEGACY_LABELS = {"rss": "Feeds", "raindrop": "Raindrop bookmarks"}
_NEW_COUNT = re.compile(r"^(\d+) new")


class CaptureBody(BaseModel):
    """Body of POST /capture: the link and, optionally, the reader's own words about it."""

    url: str = Field(min_length=1, max_length=2048)
    note: str | None = Field(default=None, max_length=2000)


def _latest_runs(session: Session) -> dict[str, RunLog]:
    """The most recent RunLog row for each source, from the last 600 rows."""
    rows = session.exec(select(RunLog).order_by(RunLog.id.desc()).limit(600)).all()  # type: ignore[attr-defined]
    latest: dict[str, RunLog] = {}
    for row in rows:
        latest.setdefault(row.source, row)
    return latest


def _iso(value: datetime | None) -> str | None:
    """ISO text of a datetime, or None."""
    return value.isoformat() if value else None


def _collector_row(key: str, label: str, run: RunLog | None) -> dict:
    """One collector's entry: its last run, outcome and new-item count."""
    match = _NEW_COUNT.match(run.detail or "") if run else None
    return {
        "key": key,
        "label": label,
        "status": run.status if run else "never",
        "detail": run.detail if run else None,
        "last_run": _iso(run.finished_at or run.started_at) if run else None,
        "new_items": int(match.group(1)) if match else None,
    }


@router.get("/sources")
def list_sources(request: Request) -> dict:
    """The subscribed feeds and the collectors, each with its last run and outcome."""
    with Session(request.app.state.engine) as session:
        counts = dict(session.exec(
            select(Item.feed_url, func.count(Item.id)).where(Item.feed_url.isnot(None))  # type: ignore[union-attr]
            .group_by(Item.feed_url)
        ).all())
        feeds = [
            {
                "id": f.id, "name": f.name, "feed_url": f.feed_url, "kind": f.kind,
                "enabled": f.enabled, "last_fetch_status": f.last_fetch_status,
                "last_fetch_at": _iso(f.last_fetch_at), "last_error": f.last_error,
                "item_count": counts.get(f.feed_url, 0), "added_via": f.added_via,
            }
            for f in session.exec(select(Feed).order_by(Feed.name)).all()
        ]
        runs = _latest_runs(session)
    collectors = [_collector_row(k, COLLECTOR_LABELS[k], runs.get(RUN_SOURCES[k]))
                  for k in COLLECTORS]
    collectors += [_collector_row(k, label, runs.get(k)) for k, label in LEGACY_LABELS.items()]
    return {"feeds": feeds, "collectors": collectors}


@router.post("/capture")
def capture(request: Request, body: CaptureBody) -> dict:
    """Add a link as a from-you item right now; returns the item (new or already known)."""
    engine = request.app.state.engine
    try:
        item_id = capture_url(engine, request.app.state.settings, body.url,
                              note=body.note, via="manual")
    except CaptureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler = getattr(request.app.state, "radar_scheduler", None)
    if scheduler is not None:
        scheduler.kick_assessment()  # judge it now rather than at the next cycle
    with Session(engine) as session:
        items = radar_items(session, [item_id])
    if not items:
        raise HTTPException(status_code=500, detail="the item was saved but could not be read back")
    return items[0]


@router.post("/collect")
def collect(request: Request, force_watch: bool = False) -> dict:
    """Start a collection and assessment cycle in the background and return at once.

    The watch sweep runs once a day; `?force_watch=true` runs it in this cycle as well, for a
    reader who explicitly asks for it.
    """
    scheduler = getattr(request.app.state, "radar_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="the scheduler is not running")
    extra = {"force_watch": True} if force_watch else {}
    if not scheduler.start_cycle_in_background("manual", **extra):
        raise HTTPException(status_code=409, detail="a collection is already running")
    return {"started": True}


@router.get("/status")
def status(request: Request) -> dict:
    """Scheduler state plus queue sizes: items waiting for an assessment or an embedding."""
    scheduler = getattr(request.app.state, "radar_scheduler", None)
    with Session(request.app.state.engine) as session:
        total = session.exec(select(func.count(Item.id))).one()
        assessed = session.exec(select(func.count(Assessment.id))).one()
        embedded = session.exec(select(func.count(Embedding.id))).one()
        last_ok = session.exec(
            select(RunLog).where(RunLog.status == "ok", RunLog.source.like("radar:%"))  # type: ignore[attr-defined]
            .order_by(RunLog.id.desc())  # type: ignore[attr-defined]
        ).first()
    base = scheduler.status() if scheduler is not None else {"scheduler_running": False}
    return {
        **base,
        "last_collect_at": _iso(last_ok.finished_at) if last_ok else None,
        "queues": {
            "unassessed": max(0, total - assessed),
            "unembedded": max(0, total - embedded),
        },
        "items_total": total,
    }
