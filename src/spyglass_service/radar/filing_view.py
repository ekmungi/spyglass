"""What the "To file" view shows besides the queue: the run's status, open questions, the plan
and what was filed recently.

Every text here is either fixed by Spyglass, the reader's own, or was cleaned to one plain line
when a run stored it (see `filing_tables.plain_line`). Times go out as ISO strings; the status
line is composed here in the reader's time zone so the view and the brief say the same thing.
"""

from datetime import datetime, timedelta

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.radar.filing_config import (
    BACKGROUND_UNAVAILABLE_LINE, background_unlocked, filing_configured,
)
from spyglass_service.radar import filing_status
from spyglass_service.radar.filing_plan import plan_rows
from spyglass_service.radar.filing_questions import open_questions
from spyglass_service.radar.filing_tables import as_utc, plain_line
from spyglass_service.radar.filing_trigger import daily_time, quiet_minutes
from spyglass_service.radar.models import ItemExtra, loads, utcnow
from spyglass_service.radar.scheduler_support import zone_for
from spyglass_service.radar.serialize import radar_items

RECENT_DAYS = 14
RECENT_MAX = 50
HEADLINE_MAX = 200


def _headlines(engine: Engine, item_ids: list[int]) -> dict[int, str]:
    """Each item's headline (or title), cleaned to one line."""
    with Session(engine) as session:
        items = radar_items(session, sorted(set(item_ids)))
    return {i["id"]: plain_line(i.get("headline") or i.get("title"), HEADLINE_MAX) for i in items}


def _when(moment: datetime | None, now: datetime, zone) -> str:
    """"today 21:05", "yesterday 21:05" or "Tue 21:05" in the reader's zone."""
    if moment is None:
        return ""
    local, today = moment.astimezone(zone), now.astimezone(zone).date()
    days = (today - local.date()).days
    label = "today" if days == 0 else "yesterday" if days == 1 else local.strftime("%a %d %b")
    return f"{label} {local:%H:%M}"


def _time(text: object) -> datetime | None:
    """A stored ISO time as an aware datetime, or None."""
    try:
        return as_utc(datetime.fromisoformat(str(text))) if text else None
    except ValueError:
        return None


def status_line(mode: str, state: dict, settings, now: datetime) -> str:
    """One plain sentence on what background filing did last and will do next."""
    zone = zone_for(settings.radar_timezone)
    if mode == "off":
        return "Background filing is off: items wait until you click File now."
    if state["state"] == "running":
        return f"Filing is running now (started {_when(_time(state['started_at']), now, zone)})."
    retry = _time(state["next_retry"])
    finished = _when(_time(state["finished_at"]), now, zone)
    if state["result"] == "stopped":
        text = f"The last run stopped {finished}: {filing_status.reason_text(state['reason'])}."
        return f"{text} Next try {_when(retry, now, zone)}." if retry else text
    if state["result"] in ("ok", "partial"):
        did = (f"{state['proposed']} proposed" if state["kind"] == "plan"
               else f"{state['filed']} filed, {state['asked']} asked")
        return f"Last run {finished}: {did}."
    return (f"Filing runs after the queue has been quiet for {quiet_minutes(settings)} minutes, "
            f"and at {daily_time(settings):%H:%M} each day.")


def status_view(engine: Engine, settings, now: datetime | None = None) -> dict:
    """The run status for the view: mode, state, last run, next try and the status line.

    While background filing is locked in this version the mode is always "off" (whatever is
    stored), `background_available` is false and the line says to use File now.
    """
    moment = now or utcnow()
    state = filing_status.read_status(engine)
    available = background_unlocked()
    mode = settings.radar_filing_mode if available else "off"
    last = None
    if state["started_at"]:
        last = {key: state[key] for key in ("kind", "started_at", "finished_at", "result",
                                            "reason", "detail", "filed", "asked", "proposed",
                                            "cost_usd", "refused")}
        last["reason_text"] = filing_status.reason_text(state["reason"]) if state["reason"] else None
    return {"mode": mode, "state": state["state"], "last_run": last,
            "next_retry": state["next_retry"],
            "line": status_line(mode, state, settings, moment) if available
            else BACKGROUND_UNAVAILABLE_LINE,
            "configured": filing_configured(settings), "background_available": available}


def questions_view(engine: Engine, now: datetime | None = None) -> list[dict]:
    """Open questions with the item's headline."""
    rows = open_questions(engine, now=now)
    names = _headlines(engine, [r["item_id"] for r in rows])
    return [{**r, "headline": names.get(r["item_id"], "")} for r in rows]


def plan_view(engine: Engine) -> list[dict]:
    """The plan rows with the item's headline."""
    rows = plan_rows(engine)
    names = _headlines(engine, [r["item_id"] for r in rows])
    return [{**r, "headline": names.get(r["item_id"], "")} for r in rows]


def recent_view(engine: Engine, now: datetime | None = None) -> list[dict]:
    """Items filed in the last 14 days, newest first: headline, note path, project, best guess."""
    cutoff = ((now or utcnow()) - timedelta(days=RECENT_DAYS)).isoformat()
    with Session(engine) as session:
        rows = session.exec(select(ItemExtra).where(
            func.json_extract(ItemExtra.data, "$.filed.at") >= cutoff)).all()
    entries = []
    for row in rows:
        filed = (loads(row.data, {}) or {}).get("filed")
        if isinstance(filed, dict) and filed.get("path"):
            entries.append((str(filed.get("at") or ""), row.item_id, filed))
    entries.sort(reverse=True)
    entries = entries[:RECENT_MAX]
    names = _headlines(engine, [e[1] for e in entries])
    return [{"item_id": item_id, "headline": names.get(item_id, ""),
             "path": plain_line(filed["path"], 500),
             "project": plain_line(filed.get("project"), 80) or None,
             "best_guess": bool(filed.get("best_guess")), "at": at}
            for at, item_id, filed in entries]
