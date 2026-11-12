"""Jobs the scheduler runs beside its collect-judge-compose cycle: live capture, upkeep and the
background filing check.

Kept apart from `scheduler.py` so that file stays small; each function here is called from it.
"""

import logging
from collections.abc import Callable
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine

from spyglass_service.backup import DEFAULT_KEEP, BackupSkipped, backup_db, list_backups
from spyglass_service.config import Settings

logger = logging.getLogger(__name__)

# How long the weekly upkeep waits for a running cycle to finish before giving up for the week.
UPKEEP_LOCK_WAIT_SECONDS = 600
# Model-usage records older than this many days are removed by the weekly upkeep.
USAGE_KEEP_DAYS = 180
# Ids of the two maintenance jobs.
UPKEEP_JOB = "radar-upkeep"
BACKUP_JOB = "radar-backup"
# The background filing check (see radar/filing_trigger.py).
FILING_JOB = "radar-filing"
# The daily backup runs at this local time unless `radar_backup_time` says otherwise.
DEFAULT_BACKUP_TIME = dtime(3, 0)
# A catch-up check takes a backup when the newest one is older than this: a day plus two hours of
# slack, so a backup that ran a little late yesterday is not repeated.
BACKUP_STALE_HOURS = 26


def start_slack_live(engine: Engine, settings: Settings, kick: Callable[[], Any]) -> Any | None:
    """Start the live Slack listener; None when it is not configured or cannot start.

    `kick` is called after each captured link so analysis starts at once. A failure here is
    logged and never stops the scheduler: the timed check of the channel still runs.
    """
    try:
        from spyglass_service.radar.sources.slack_live import SlackLiveListener

        listener = SlackLiveListener(engine, settings, on_capture=lambda _item_id: kick())
        return listener if listener.start() else None
    except Exception:
        logger.exception("the live Slack listener could not start")
        return None


def stop_slack_live(listener: Any | None) -> None:
    """Stop the live Slack listener if one is running; never raises."""
    if listener is None:
        return
    try:
        listener.stop()
    except Exception:
        logger.exception("the live Slack listener did not stop cleanly")


def slack_live_status(listener: Any | None) -> dict | None:
    """The listener's status for the status endpoint, or None when it is not running."""
    if listener is None:
        return None
    try:
        return listener.status()
    except Exception:
        logger.exception("the live Slack listener status could not be read")
        return None


def weekly_upkeep(engine: Engine, settings: Settings, acquire: Callable[[float], bool],
                  release: Callable[[], None]) -> dict | None:
    """Run the weekly upkeep under the cycle lock; None when a cycle held the lock too long.

    Upkeep deletes old stored text and logs, so it must never run while a cycle is reading
    or writing the same rows.
    """
    from spyglass_service.radar.housekeeping import run_housekeeping

    if not acquire(UPKEEP_LOCK_WAIT_SECONDS):
        logger.info("weekly upkeep skipped: a cycle was still running")
        return None
    try:
        report = run_housekeeping(engine, settings)
        return {**report, "usage": _prune_usage(engine)}
    finally:
        release()


def _prune_usage(engine: Engine) -> Any:
    """Trim old model-usage records when the usage module exists; never raises.

    The module is optional and imported here, so the upkeep works whether or not it is present.
    """
    try:
        from spyglass_service.radar.usage import prune_usage
    except ImportError:
        return {"skipped": "no usage records are kept"}
    try:
        return {"deleted": prune_usage(engine, USAGE_KEEP_DAYS)}
    except Exception as exc:  # noqa: BLE001 -- one failed step must not fail the upkeep
        logger.exception("pruning old usage records failed")
        return {"error": f"{type(exc).__name__}: {exc}"}


def backup_time(settings: Settings) -> dtime:
    """The local time of the daily backup (`radar_backup_time`, "HH:MM"); 03:00 when unreadable."""
    text = str(getattr(settings, "radar_backup_time", "") or "")
    try:
        hours, minutes = text.strip().split(":")
        return dtime(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return DEFAULT_BACKUP_TIME


def register_maintenance_jobs(scheduler: Any, in_thread: Callable[..., Callable[[], None]],
                              engine: Engine, settings: Settings, acquire: Callable[[float], bool],
                              release: Callable[[], None], zone: Any) -> None:
    """Add the weekly upkeep (Sunday 03:30), the daily backup and the filing check.

    The upkeep and the backup run in their own thread and take the cycle lock, so neither runs
    during a cycle; the filing check waits for a cycle to end instead.
    """
    when = backup_time(settings)
    scheduler.add_job(in_thread(lambda: weekly_upkeep(engine, settings, acquire, release),
                                "radar-upkeep"),
                      CronTrigger(day_of_week="sun", hour=3, minute=30, timezone=zone),
                      id=UPKEEP_JOB)
    scheduler.add_job(in_thread(lambda: daily_backup(engine, settings, acquire, release),
                                "radar-backup"),
                      CronTrigger(hour=when.hour, minute=when.minute, timezone=zone),
                      id=BACKUP_JOB)
    register_filing_check(scheduler, in_thread, engine, settings)


def register_filing_check(scheduler: Any, in_thread: Callable[..., Callable[[], None]],
                          engine: Engine, settings: Settings) -> None:
    """Add the background filing check (every few minutes; it does nothing while the mode is off).

    The check reads the settings each time, so switching the mode on or off needs no restart.
    It skips a tick while a cycle holds the cycle lock, but never takes that lock itself.
    """
    from spyglass_service.radar.filing_trigger import TICK_MINUTES, filing_tick

    scheduler.add_job(in_thread(lambda: filing_tick(engine, settings), FILING_JOB),
                      "interval", minutes=TICK_MINUTES, id=FILING_JOB)


def _database(settings: Settings) -> tuple[Path, Path, int] | None:
    """(database file, backups folder, copies to keep), or None when settings name no database."""
    db_path, folder = getattr(settings, "db_path", None), getattr(settings, "backups_dir", None)
    if db_path is None or folder is None or not Path(db_path).exists():
        return None
    return Path(db_path), Path(folder), int(getattr(settings, "backup_keep", DEFAULT_KEEP))


def daily_backup(engine: Engine, settings: Settings, acquire: Callable[[float], bool],
                 release: Callable[[], None]) -> Path | None:
    """Back up the database under the cycle lock and log the outcome; None when nothing was taken.

    The lock keeps the copy from being made while a cycle writes. A failure is recorded as a run
    log row and never raised, because a scheduled job has nobody to raise it to.
    """
    from spyglass_service.radar.sources._common import log_run

    target = _database(settings)
    if target is None:
        return None
    if not acquire(UPKEEP_LOCK_WAIT_SECONDS):
        logger.info("daily backup postponed: a cycle was still running")
        return None
    started = datetime.now()
    try:
        path = backup_db(target[0], backups_dir=target[1], keep=target[2])
        log_run(engine, "backup", "ok", f"backup written: {path.name}" if path else "no database",
                started)
        return path
    except BackupSkipped as exc:
        logger.warning("%s", exc)
        log_run(engine, "backup", "skipped", str(exc), started)
        return None
    except Exception as exc:  # noqa: BLE001 -- recorded in the run log, shown in Activity
        logger.exception("the daily backup failed")
        log_run(engine, "backup", "error", f"{type(exc).__name__}: {exc}", started)
        return None
    finally:
        release()


def backup_catchup(engine: Engine, settings: Settings, acquire: Callable[[float], bool],
                   release: Callable[[], None], now: datetime) -> bool:
    """Take a backup when the newest one is over `BACKUP_STALE_HOURS` old; True when one was taken.

    This covers a PC that was asleep at the backup hour. The scheduler's 30-minute catch-up check
    calls it, so after a stale gap exactly one backup is taken (the next check finds it fresh).
    A running cycle postpones it to the next check.
    """
    target = _database(settings)
    if target is None:
        return False
    backups = list_backups(target[1])
    if backups:
        age = now.timestamp() - max(p.stat().st_mtime for p in backups)
        if age <= BACKUP_STALE_HOURS * 3600:
            return False
    return _backup_now(engine, settings, acquire, release)


def _backup_now(engine: Engine, settings: Settings, acquire: Callable[[float], bool],
                release: Callable[[], None]) -> bool:
    """Take the catch-up backup if the lock is free right now (no waiting)."""
    return daily_backup(engine, settings, lambda _wait: acquire(0), release) is not None
