"""The radar's in-process scheduler: collects, assesses and composes without any other program.

A cycle is: the engine's own collectors, the radar collectors, Raindrop marking, embeddings,
the assessment pipeline and watch linking. Recurring jobs run on APScheduler's background
scheduler: a cycle every `radar_collect_hours`, the daily brief at `radar_brief_time` (cycle
first, then compose), a poll for links sent in through Slack or Gmail (every
`radar_capture_poll_seconds`, 60 seconds by default), and a
catch-up check every 30 minutes that composes today's brief when it is missing after the brief
time (a PC that slept through the brief time, or a brief that was skipped or failed) and takes a
database backup when the newest is over 26 hours old. A daily backup and a weekly upkeep run under
the cycle lock (see `scheduler_extras`).

Jobs never expire: a job missed while the PC slept runs on wake (`misfire_grace_time=None`),
and several missed runs collapse into one. Each job runs in a daemon thread, so a stuck cycle
never keeps the process alive after `stop()`, which asks the running cycle to end between
stages and pipeline batches and waits a bounded time for it. A lock in this process and a lock
file in the data directory guarantee that two cycles never overlap, even across processes.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine

from spyglass_service.config import Settings
from spyglass_service.radar.cycle_lock import CycleFileLock, PidAlive, pid_alive
from spyglass_service.radar.models import utcnow
from spyglass_service.radar.scheduler_stages import Stage, StagesMixin
from spyglass_service.radar.scheduler_extras import (
    backup_catchup,
    register_maintenance_jobs,
    slack_live_status,
    start_slack_live,
    stop_slack_live,
)
from spyglass_service.radar.scheduler_support import (
    brief_detail,
    brief_exists,
    cycle_result,
    needs_catchup,
    parse_brief_time,
    zone_for,
)

__all__ = ["RadarScheduler", "needs_catchup", "parse_brief_time", "brief_detail"]

logger = logging.getLogger(__name__)

CYCLE_JOB = "radar-cycle"
BRIEF_JOB = "radar-brief"
CAPTURE_JOB = "radar-capture-poll"
CATCHUP_JOB = "radar-catchup"
# Minutes between catch-up checks (is today's brief missing although its time has passed?).
CATCHUP_MINUTES = 30
# Seconds after start before the first catch-up check, so service startup is never delayed.
CATCHUP_DELAY_SECONDS = 15
# Longest the daily brief waits for a running cycle; after that it is recorded as skipped and
# the next catch-up check composes it.
BRIEF_WAIT_SECONDS = 3600
# Longest `stop()` waits for a running cycle to reach a stopping point.
STOP_WAIT_SECONDS = 15
# The inter-process lock file, inside the data directory.
LOCK_FILE = "radar-cycle.lock"
# Jobs never expire (a PC asleep at the brief time still gets its brief on wake), and missed
# runs of one job collapse into a single run.
JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": None}
FULL_CYCLE = ("legacy", "radar", "raindrop", "embed", "pipeline", "watch")

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    """The current time as aware UTC."""
    return datetime.now(UTC)


class RadarScheduler(StagesMixin):
    """Runs the radar's recurring work in the background.

    Args:
        engine: Database engine.
        settings: Runtime settings (read again at every catch-up check, so changes apply).
        get_index: Callable returning the embedding index (created lazily by the service).
        stages: Replacement stage callables keyed legacy, radar, raindrop, embed, pipeline,
            watch, compose (tests).
        clock: Returns the current aware UTC time (tests simulate a sleeping PC with it).
        pid_alive: Liveness check used by the inter-process lock (tests).
    """

    def __init__(self, engine: Engine, settings: Settings, get_index: Callable[[], Any], *,
                 stages: Mapping[str, Stage] | None = None, clock: Clock | None = None,
                 pid_alive: PidAlive = pid_alive) -> None:
        self._engine = engine
        self._settings = settings
        self._get_index = get_index
        self._overrides = dict(stages or {})
        self._clock = clock or _utc_now
        self._cycle_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._kick_pending = threading.Event()
        self._last_cycle: dict | None = None
        self._last_brief: dict | None = None
        self._last_check: dict | None = None
        self._brief_day: str | None = None
        self._force_watch = False
        self.slack_live: Any | None = None
        self._applied = self._wanted_schedule()
        data_dir = getattr(settings, "data_dir", None)
        self._file_lock = (CycleFileLock(Path(data_dir) / LOCK_FILE, pid_alive=pid_alive)
                           if data_dir else None)
        self._scheduler = BackgroundScheduler(timezone=zone_for(settings.radar_timezone),
                                              job_defaults=JOB_DEFAULTS)

    # ---- locking --------------------------------------------------------------------------

    @property
    def lock_path(self) -> Path | None:
        """The inter-process lock file, or None when there is no data directory (tests)."""
        return self._file_lock.path if self._file_lock else None

    def _acquire(self, wait_seconds: float) -> bool:
        """Take the in-process lock (waiting up to `wait_seconds`) and the lock file."""
        got = (self._cycle_lock.acquire(timeout=wait_seconds) if wait_seconds > 0
               else self._cycle_lock.acquire(blocking=False))
        if not got:
            return False
        if self._file_lock is not None and not self._file_lock.acquire():
            self._cycle_lock.release()
            logger.warning("another Spyglass process is running a radar cycle; not starting one")
            return False
        return True

    def _release(self) -> None:
        """Run any assessment requested meanwhile, then release both locks."""
        try:
            self._drain_kicks()
        finally:
            if self._file_lock is not None:
                self._file_lock.release()
            self._cycle_lock.release()

    def _drain_kicks(self) -> None:
        """Embed and assess again when a capture asked for it while the lock was held."""
        while self._kick_pending.is_set() and not self._stop_event.is_set():
            self._kick_pending.clear()
            self._run_stages(["embed", "pipeline"])

    # ---- cycles ---------------------------------------------------------------------------

    @property
    def brief_day(self) -> str | None:
        """The day the running cycle composes (fixed when the cycle started), else None."""
        return self._brief_day

    @property
    def forcing_watch(self) -> bool:
        """True while a cycle started with the reader's "run the watch sweep now" request."""
        return self._force_watch

    def _cycle_body(self, trigger: str, compose: bool, day: date | None) -> dict:
        """Run a full cycle (lock already held) and record the outcome for `status()`."""
        started = utcnow()
        names = list(FULL_CYCLE) + (["compose"] if compose else [])
        self._brief_day = day.isoformat() if day else None
        try:
            stages = self._run_stages(names)
        finally:
            self._brief_day, self._force_watch = None, False
        stopped = self._stop_event.is_set() and len(stages) < len(names)
        result = {
            "trigger": trigger,
            "started_at": started.isoformat(),
            "finished_at": utcnow().isoformat(),
            "result": cycle_result(stages, stopped),
            "failed_stages": [n for n, r in stages.items() if not r["ok"]],
            "stages": stages,
        }
        reasons = [r["reason"] for r in stages.values() if r.get("reason")]
        if reasons:
            result["reasons"] = reasons
        if compose:
            self._record_brief(day or self._now().date(), stages.get("compose"))
        with self._state_lock:
            self._last_cycle = result
        return result

    def run_cycle(self, trigger: str = "manual", *, compose: bool = False,
                  wait_seconds: float = 0, day: date | None = None) -> dict:
        """Run a cycle now, waiting up to `wait_seconds` for one already running.

        Returns:
            The cycle result, or {"result": "busy"} when another cycle (in this process or
            another one) holds the lock.
        """
        if not self._acquire(wait_seconds):
            return {"result": "busy", "trigger": trigger}
        try:
            return self._cycle_body(trigger, compose, day)
        finally:
            self._release()

    def start_cycle_in_background(self, trigger: str = "manual", *,
                                  force_watch: bool = False) -> bool:
        """Start a cycle in a thread and return at once; False when one is already running.

        force_watch runs the watch sweep even when it ran less than a day ago.
        """
        if not self._acquire(0):
            return False
        self._force_watch = force_watch

        def work() -> None:
            try:
                self._cycle_body(trigger, compose=False, day=None)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="radar-cycle").start()
        return True

    def kick_assessment(self) -> bool:
        """Embed and assess new items in a thread (after a capture).

        When a cycle is running, the request is remembered and runs right after it; returns
        False in that case, True when the assessment started now.
        """
        if not self._acquire(0):
            self._kick_pending.set()
            return False
        self._kick_pending.clear()

        def work() -> None:
            try:
                self._run_stages(["embed", "pipeline"])
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="radar-assess").start()
        return True

    @property
    def running(self) -> bool:
        """True while a cycle holds the lock."""
        return self._cycle_lock.locked()

    # ---- jobs -----------------------------------------------------------------------------

    def _now(self) -> datetime:
        """The current time in the brief's time zone (read from settings every time)."""
        return self._clock().astimezone(zone_for(self._settings.radar_timezone))

    def _scheduled_cycle(self) -> None:
        """Interval job: a plain cycle."""
        self.run_cycle("schedule")

    def _daily_brief(self) -> None:
        """Daily job: a cycle, then compose, waiting for a running cycle if need be.

        The brief's day is fixed now, at the scheduled time, so a cycle that runs past
        midnight does not label the brief with the next date. When the wait runs out the
        brief is recorded as skipped; the next catch-up check composes it.
        """
        now = self._now()
        result = self.run_cycle("daily-brief", compose=True, wait_seconds=BRIEF_WAIT_SECONDS,
                                day=now.date())
        if result["result"] == "busy":
            reason = (f"A collection cycle was still running after {BRIEF_WAIT_SECONDS:g} "
                      f"seconds; the brief will be composed at the next check (every "
                      f"{CATCHUP_MINUTES} minutes).")
            logger.warning("daily brief for %s skipped: %s", now.date(), reason)
            self._set_last_brief(now.date(), "skipped", reason)

    def catchup(self) -> bool:
        """Compose today's brief (cycle first) when it is missing and its time has passed.

        Runs every 30 minutes. It first applies a changed brief time or time zone to the daily
        job. Returns True when a cycle with compose ran.
        """
        self._apply_schedule_changes()
        now = self._now()
        backup_catchup(self._engine, self._settings, self._acquire, self._release, now)  # sleeping PC
        exists = brief_exists(self._engine, now.date())
        if not needs_catchup(now, parse_brief_time(self._settings.radar_brief_time), exists):
            self._set_last_check(now, "brief exists" if exists else "before brief time")
            return False
        result = self.run_cycle("catch-up", compose=True, day=now.date())
        if result["result"] == "busy":
            self._set_last_check(now, "busy: a cycle is running; checking again later")
            return False
        self._set_last_check(now, "composed")
        return True

    def _wanted_schedule(self) -> tuple[str, str]:
        """The brief time and time zone the settings ask for now."""
        return (str(self._settings.radar_brief_time), self._settings.radar_timezone or "")

    def _apply_schedule_changes(self) -> None:
        """Move the daily job when the brief time or time zone changed since it was set."""
        wanted = self._wanted_schedule()
        if wanted == self._applied:
            return
        self._applied = wanted
        if self._scheduler.running and self._scheduler.get_job(BRIEF_JOB) is not None:
            when = parse_brief_time(wanted[0])
            self._scheduler.reschedule_job(BRIEF_JOB, trigger=CronTrigger(
                hour=when.hour, minute=when.minute, timezone=zone_for(wanted[1])))
            logger.info("daily brief moved to %s (%s)", wanted[0], wanted[1] or "local time")

    # ---- lifecycle ------------------------------------------------------------------------

    @staticmethod
    def _in_thread(target: Callable[[], Any], name: str) -> Callable[[], None]:
        """A job function that runs `target` in a daemon thread and returns at once."""
        def job() -> None:
            threading.Thread(target=target, daemon=True, name=name).start()
        return job

    def start(self) -> None:
        """Register the jobs and start the background scheduler (idempotent)."""
        if self._scheduler.running:
            return
        self._stop_event.clear()
        self._applied = self._wanted_schedule()
        when = parse_brief_time(self._settings.radar_brief_time)
        hours = max(0.25, float(self._settings.radar_collect_hours))
        now = _utc_now()
        add = self._scheduler.add_job
        add(self._in_thread(self._scheduled_cycle, "radar-cycle"), "interval", hours=hours,
            id=CYCLE_JOB, next_run_time=now + timedelta(hours=hours))
        add(self._in_thread(self._daily_brief, "radar-brief"), CronTrigger(
            hour=when.hour, minute=when.minute, timezone=zone_for(self._settings.radar_timezone)),
            id=BRIEF_JOB)
        if self._settings.slack_bot_token or self._settings.gmail_app_password:
            add(self._in_thread(self.poll_captures, "radar-capture"), "interval",
                seconds=max(15, int(getattr(self._settings, "radar_capture_poll_seconds", 60))),
                id=CAPTURE_JOB)
        add(self._in_thread(self.catchup, "radar-catchup"), "interval", minutes=CATCHUP_MINUTES,
            id=CATCHUP_JOB, next_run_time=now + timedelta(seconds=CATCHUP_DELAY_SECONDS))
        register_maintenance_jobs(self._scheduler, self._in_thread, self._engine, self._settings,
                                  self._acquire, self._release, zone_for(self._settings.radar_timezone))
        self._scheduler.start()
        self.slack_live = start_slack_live(self._engine, self._settings, self.kick_assessment)

    def stop(self, wait_seconds: float = STOP_WAIT_SECONDS) -> bool:
        """Stop the jobs, ask a running cycle to end, and wait up to `wait_seconds` for it.

        Returns True when no cycle is running any more, False when one was still running when
        the wait ran out (it runs in a daemon thread, so it does not keep the process alive).
        """
        self._stop_event.set()
        stop_slack_live(self.slack_live)
        self.slack_live = None
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._cycle_lock.acquire(timeout=max(0.0, wait_seconds)):
            self._cycle_lock.release()
            return True
        logger.warning("a radar cycle was still running %ss after the stop request",
                       wait_seconds)
        return False

    def _next_run(self, job_id: str) -> str | None:
        """ISO time of a job's next run, or None when it is not scheduled."""
        job = self._scheduler.get_job(job_id) if self._scheduler.running else None
        when = getattr(job, "next_run_time", None)
        return when.isoformat() if when else None

    def status(self) -> dict:
        """A snapshot for the status endpoint: running flags, last results and next runs."""
        with self._state_lock:
            last, brief, check = self._last_cycle, self._last_brief, self._last_check
        return {
            "scheduler_running": self._scheduler.running,
            "cycle_running": self.running,
            "stopping": self._stop_event.is_set(),
            "kick_pending": self._kick_pending.is_set(),
            "last_cycle": last,
            "last_brief": brief,
            "last_check": check,
            "next_cycle_at": self._next_run(CYCLE_JOB),
            "next_brief_at": self._next_run(BRIEF_JOB),
            "next_capture_poll_at": self._next_run(CAPTURE_JOB),
            "next_check_at": self._next_run(CATCHUP_JOB),
            "brief_time": self._settings.radar_brief_time,
            "timezone": str(zone_for(self._settings.radar_timezone)),
            "collect_hours": self._settings.radar_collect_hours,
            "slack_live": slack_live_status(self.slack_live),
        }
