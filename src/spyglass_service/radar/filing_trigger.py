"""When a background filing run starts by itself: after a quiet period, or at the daily time.

The scheduler calls `filing_tick` every two minutes. Nothing happens while the mode is "off".
Otherwise a run starts when there is work (`filing_run.plan_work`) and either the queue has been
quiet for `radar_filing_quiet_minutes` (no item added, no answer submitted, no plan approved), or
the daily safety time `radar_filing_daily_time` has passed today and no run started since. A run
never starts while another runs, before the retry time a stopped or partial run set, or while a
collection cycle holds its lock.

Why skip during a cycle rather than share the database: the run's own writes are a few
single-row transactions through this service, which SQLite in WAL mode serialises safely, so the
database does not need the cycle lock. But a cycle and a filing session are both heavy (model
calls, embeddings, a full Claude Code start-up), so the run waits for the next tick instead of
competing with a cycle; it does not hold the cycle lock, so it never delays collection.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, func, select

from spyglass_service.radar.filing_config import effective_mode, filing_configured
from spyglass_service.radar import filing_status
from spyglass_service.radar.cycle_lock import MAX_LOCK_AGE, pid_alive
from spyglass_service.radar.filing_plan import last_decision_at
from spyglass_service.radar.filing_questions import expire_questions
from spyglass_service.radar.filing_queue import FilingRow
from spyglass_service.radar.filing_tables import FilingQuestion, as_utc
from spyglass_service.radar.models import utcnow
from spyglass_service.radar.scheduler_support import zone_for

logger = logging.getLogger(__name__)

TICK_MINUTES = 2
QUIET_MIN, QUIET_MAX = 2, 240
DEFAULT_DAILY = dtime(21, 0)
CYCLE_LOCK_FILE = "radar-cycle.lock"


def daily_time(settings) -> dtime:
    """The daily safety time (`radar_filing_daily_time`, "HH:MM"); 21:00 when unreadable."""
    text = str(getattr(settings, "radar_filing_daily_time", "") or "")
    try:
        hours, minutes = text.strip().split(":")
        return dtime(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return DEFAULT_DAILY


def quiet_minutes(settings) -> int:
    """The quiet period in minutes, kept between 2 and 240."""
    try:
        value = int(getattr(settings, "radar_filing_quiet_minutes", 10))
    except (TypeError, ValueError):
        value = 10
    return min(max(value, QUIET_MIN), QUIET_MAX)


def last_activity(engine: Engine) -> datetime | None:
    """The latest of: an item queued, an answer submitted, a plan approved (None when none)."""
    with Session(engine) as session:
        queued = session.exec(select(func.max(FilingRow.requested_at))).one()
        answered = session.exec(select(func.max(FilingQuestion.answered_at))).one()
    times = [as_utc(t) for t in (queued, answered, last_decision_at(engine)) if t is not None]
    return max(times) if times else None


def cycle_busy(settings) -> bool:
    """True while a collection cycle holds its lock file (a live holder, not a stale file)."""
    path = Path(settings.data_dir) / CYCLE_LOCK_FILE
    try:
        holder = json.loads(path.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(holder["started_at"])
        pid = int(holder["pid"])
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True  # being written right now, or unreadable: treat as busy for one tick
    if utcnow() - as_utc(started) > MAX_LOCK_AGE:
        return False
    return pid_alive(pid)


def daily_due(now_local: datetime, at: dtime, last_started_local: datetime | None) -> bool:
    """True when today's daily time has passed and no run started since it."""
    today_at = now_local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return now_local >= today_at and (last_started_local is None or last_started_local < today_at)


def decide(now: datetime, *, mode: str, has_work: bool, activity: datetime | None,
           quiet: timedelta, daily: dtime, last_started: datetime | None,
           next_retry: datetime | None, running: bool, busy: bool, zone) -> str | None:
    """Why a run should start now ("daily" or "quiet"), or None. All times are aware."""
    if mode not in ("auto", "plan_first") or not has_work or running or busy:
        return None
    if next_retry is not None and now < next_retry:
        return None
    local_started = last_started.astimezone(zone) if last_started else None
    if daily_due(now.astimezone(zone), daily, local_started):
        return "daily"
    if activity is None or now - activity >= quiet:
        return "quiet"
    return None


def _time(text: object) -> datetime | None:
    """A stored ISO time as an aware datetime, or None."""
    try:
        return as_utc(datetime.fromisoformat(str(text))) if text else None
    except ValueError:
        return None


def filing_tick(engine: Engine, settings, *, now: datetime | None = None,
                runner: Callable[[Engine, object], dict] | None = None,
                busy: Callable[[object], bool] = cycle_busy) -> str | None:
    """One scheduler check: expire old questions, then start a run when one is due.

    Returns the reason a run was started ("daily" or "quiet"), or None. Never raises: a scheduled
    job has nobody to raise to, so a failure is logged.
    """
    # Locked in this version: without the developer unlock the mode counts as "off", whatever
    # an earlier run left stored.
    mode = effective_mode(settings)
    # Filing that is not set up (no vault folder or no vault skill names) never starts a run.
    if mode == "off" or not filing_configured(settings):
        return None
    try:
        from spyglass_service.radar.filing_run import plan_work, run_filing

        moment = now or utcnow()
        expire_questions(engine, now=moment)
        state = filing_status.read_status(engine)
        reason = decide(moment, mode=mode, has_work=plan_work(engine, mode) is not None,
                        activity=last_activity(engine),
                        quiet=timedelta(minutes=quiet_minutes(settings)),
                        daily=daily_time(settings), last_started=_time(state["started_at"]),
                        next_retry=_time(state["next_retry"]),
                        running=state["state"] == "running" and not _stale(state, moment),
                        busy=busy(settings), zone=zone_for(settings.radar_timezone))
        if reason:
            logger.info("starting a background filing run (%s)", reason)
            (runner or run_filing)(engine, settings)
        return reason
    except Exception:  # noqa: BLE001 -- a scheduled job must never die on one bad check
        logger.exception("the background filing check failed")
        return None


def _stale(state: dict, now: datetime) -> bool:
    """A "running" record older than any run could take (the run lock decides for real)."""
    started = _time(state.get("started_at"))
    return started is None or now - started > timedelta(hours=2)
