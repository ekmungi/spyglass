"""Pure helpers for the radar scheduler: time parsing, zones and judging a stage's outcome.

Kept apart from the scheduler class so the decisions (is a brief due, did a stage really
succeed) can be read and tested without threads or a running scheduler.
"""

import json
import logging
import os
from datetime import UTC, date, datetime, time as dtime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.models import RadarBrief

logger = logging.getLogger(__name__)

# Records when the last collection cycle finished, inside the data folder, so a restart can
# tell a fresh collection from a stale one.
LAST_CYCLE_FILE = "radar-last-cycle.json"
# How long after opening the first collection runs when the last one is stale or unknown: long
# enough for the service to finish starting, short enough to feel immediate.
FIRST_CYCLE_DELAY = timedelta(seconds=60)


def parse_brief_time(text: str) -> dtime:
    """Parse "HH:MM" into a time; falls back to 06:30 for anything unreadable."""
    try:
        hours, minutes = text.strip().split(":")
        return dtime(int(hours), int(minutes))
    except (ValueError, AttributeError):
        logger.warning("invalid radar_brief_time %r; using 06:30", text)
        return dtime(6, 30)


def needs_catchup(now: datetime, brief_time: dtime, brief_exists_today: bool) -> bool:
    """True when today's brief is missing and the daily brief time has already passed.

    Args:
        now: The current local time.
        brief_time: The configured daily brief time.
        brief_exists_today: Whether a brief for today's local date is stored.
    """
    return (not brief_exists_today) and now.time() >= brief_time


def brief_exists(engine: Engine, day: date) -> bool:
    """Whether a brief for `day` is stored."""
    with Session(engine) as session:
        return session.exec(
            select(RadarBrief.id).where(RadarBrief.day == day.isoformat())
        ).first() is not None


def zone_for(name: str | None) -> tzinfo:
    """The IANA zone `name`, or the machine's own zone when it is empty or unknown."""
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 -- an unknown name falls back to the machine's zone
            logger.warning("unknown radar_timezone %r; using the machine's time zone", name)
    import tzlocal

    return tzlocal.get_localzone()


def brief_detail(value: Any) -> str:
    """A short text for a stage's return value (counts, dicts or a message)."""
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())[:200]
    return str(value)[:200] if value is not None else ""


def _count(value: dict, key: str) -> int:
    """An integer count from a stage's result dict (0 when missing or not a number)."""
    try:
        return int(value.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def pipeline_outcome(value: Any) -> tuple[str, str | None]:
    """Judge the assessment pipeline's counts: ("ok" | "partial" | "error", reason or None).

    An outage is not success: when the model could not be reached for any item the stage is
    "partial", and "error" when nothing at all could be judged. Unusable replies are partial.
    """
    if not isinstance(value, dict):
        return "ok", None
    unreachable, failed = _count(value, "unreachable"), _count(value, "failed")
    judged = _count(value, "triaged") + _count(value, "digested")
    if unreachable and not judged:
        return "error", (f"The AI service could not be reached; {unreachable} items could not "
                         "be judged and will be retried on the next run.")
    reasons = []
    if unreachable:
        reasons.append(f"The AI service could not be reached for {unreachable} items; they "
                       "will be retried on the next run.")
    if failed - unreachable > 0:
        reasons.append(f"{failed - unreachable} items got an unusable reply from the AI service.")
    if value.get("stopped"):
        reasons.append("The run stopped early because the service is shutting down.")
    return ("partial", " ".join(reasons)) if reasons else ("ok", None)


def stage_outcome(name: str, value: Any) -> dict:
    """The recorded result of a stage that returned `value` (it did not raise)."""
    status, reason = pipeline_outcome(value) if name == "pipeline" else ("ok", None)
    outcome = {"ok": status == "ok", "status": status, "detail": brief_detail(value)}
    if reason:
        outcome["reason"] = reason
    return outcome


def cycle_result(stages: dict[str, dict], stopped: bool) -> str:
    """Overall result of a cycle: ok, partial, error (every stage raised) or stopped."""
    if stopped:
        return "stopped"
    bad = [s for s in stages.values() if not s["ok"]]
    if not bad:
        return "ok"
    if len(bad) == len(stages) and all(s["status"] == "error" for s in bad):
        return "error"
    return "partial"


def first_cycle_at(now: datetime, last_finished: datetime | None, interval: timedelta) -> datetime:
    """When the first interval cycle after opening should run.

    Args:
        now: The current aware time.
        last_finished: When the last cycle finished, or None when unknown.
        interval: The time between collection cycles.

    Returns:
        A minute from now when no cycle is known or the last one is older than `interval`,
        else the last finish time plus `interval` (the normal rhythm continues).
    """
    if last_finished is None or now - last_finished > interval:
        return now + FIRST_CYCLE_DELAY
    return last_finished + interval


def read_last_finished(data_dir: Path | str | None) -> datetime | None:
    """The finish time stored by `write_last_finished`; None when missing or unreadable."""
    if not data_dir:
        return None
    try:
        raw = json.loads((Path(data_dir) / LAST_CYCLE_FILE).read_text(encoding="utf-8"))
        when = datetime.fromisoformat(raw["finished_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def write_last_finished(data_dir: Path | str | None, finished_at: datetime) -> None:
    """Store a cycle's finish time atomically (temp file, then replace); never raises.

    A failed write only costs an early collection at the next start, so it is logged and
    ignored rather than failing the cycle that just finished.
    """
    if not data_dir:
        return
    target = Path(data_dir) / LAST_CYCLE_FILE
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_text(json.dumps({"finished_at": finished_at.isoformat()}), encoding="utf-8")
        os.replace(temp, target)
    except OSError as error:
        logger.warning("could not record the last cycle time: %s", error)
