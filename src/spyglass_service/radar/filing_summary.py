"""The one filing line under the daily brief's masthead, shown only when there is something to say.

Examples: "Filed yesterday: 9 items. 2 questions are open.", "A filing plan of 4 items waits for
your approval.", or, when background filing is on but has been stopping, "Filing has not run since
Tuesday: Obsidian was closed." Returns None when there is nothing to say.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.radar import filing_status
from spyglass_service.radar.filing_config import effective_mode
from spyglass_service.radar.filing_plan import plan_rows
from spyglass_service.radar.filing_questions import open_questions
from spyglass_service.radar.filing_queue import count
from spyglass_service.radar.filing_tables import as_utc
from spyglass_service.radar.models import ItemExtra, utcnow
from spyglass_service.radar.scheduler_support import zone_for

logger = logging.getLogger(__name__)

# A run that keeps stopping is pointed out once the last good run is this old.
STALE_AFTER = timedelta(hours=24)


def _plural(n: int, one: str, many: str) -> str:
    """"1 item" or "3 items"."""
    return f"{n} {one if n == 1 else many}"


def filed_on(engine: Engine, day_start: datetime, day_end: datetime) -> int:
    """How many items were filed between two aware times."""
    filed_at = func.json_extract(ItemExtra.data, "$.filed.at")
    with Session(engine) as session:
        return int(session.exec(select(func.count()).select_from(ItemExtra).where(
            filed_at >= _utc(day_start), filed_at < _utc(day_end))).one())


def _utc(moment: datetime) -> str:
    """An aware time as the UTC ISO text the filed entries use."""
    return as_utc(moment).isoformat()


def _stalled(engine: Engine, settings, now: datetime) -> str | None:
    """"Filing has not run since Tuesday: Obsidian was closed." when runs keep stopping."""
    state = filing_status.read_status(engine)
    if _mode(settings) == "off" or state["result"] != "stopped" or not count(engine):
        return None
    last = state["last_ran_at"]
    reason = filing_status.reason_text(state["reason"])
    if not last:
        return f"Filing has not run yet: {reason}."
    last_time = as_utc(datetime.fromisoformat(last))
    if now - last_time < STALE_AFTER:
        return None
    day = last_time.astimezone(zone_for(getattr(settings, "radar_timezone", ""))).strftime("%A")
    return f"Filing has not run since {day}: {reason}."


def _mode(settings) -> str:
    """The background filing mode ("off" when the settings do not name one)."""
    return effective_mode(settings)


def filing_summary(engine: Engine, settings, now: datetime | None = None) -> dict | None:
    """{"line", "filed_yesterday", "questions", "plan"} or None when there is nothing to say.

    Never raises: the brief must load even when this line cannot be worked out.
    """
    try:
        return _summary(engine, settings, now or utcnow())
    except Exception:  # noqa: BLE001 -- the line is optional; the brief is not
        logger.exception("the filing line for the brief could not be worked out")
        return None


def _summary(engine: Engine, settings, moment: datetime) -> dict | None:
    """The body of `filing_summary`."""
    zone = zone_for(getattr(settings, "radar_timezone", ""))
    today = moment.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    filed = filed_on(engine, today - timedelta(days=1), today)
    questions = len(open_questions(engine, now=moment))
    waiting_plan = len([r for r in plan_rows(engine) if r["decision"] == "pending"])
    parts: list[str] = []
    stalled = _stalled(engine, settings, moment)
    if stalled:
        parts.append(stalled)
    if filed:
        parts.append(f"Filed yesterday: {_plural(filed, 'item', 'items')}.")
    if questions:
        parts.append(f"{_plural(questions, 'question is', 'questions are')} open.")
    if waiting_plan:
        parts.append(f"A filing plan of {_plural(waiting_plan, 'item', 'items')} waits for your "
                     "approval.")
    if not parts:
        return None
    return {"line": " ".join(parts), "filed_yesterday": filed, "questions": questions,
            "plan": waiting_plan}
