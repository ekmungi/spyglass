"""Regression tests for an unattended PC: a missed brief time, a busy cycle at brief time, a
full-day model outage, changed settings, stopping mid-cycle and a capture during a cycle."""

import threading
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from spyglass_service.radar.models import RadarBrief, dumps
from spyglass_service.radar.scheduler import BRIEF_JOB, CATCHUP_JOB, RadarScheduler

from .test_sources_support import make_engine, make_settings

STAGES = ("legacy", "radar", "raindrop", "embed", "pipeline", "watch", "compose")


class Clock:
    """A settable clock returning aware UTC times."""

    def __init__(self, now: datetime) -> None:
        """Start at `now`."""
        self.now = now

    def __call__(self) -> datetime:
        """The current simulated time."""
        return self.now


def _scheduler(engine, calls: list[str], clock=None, settings=None, **overrides) -> RadarScheduler:
    """A scheduler whose stages only record their names (or run the given overrides)."""
    def stage(name):
        def run():
            calls.append(name)
            return {"n": 1}
        return run

    stages = {name: stage(name) for name in STAGES}
    stages.update(overrides)
    return RadarScheduler(engine, settings or make_settings(radar_timezone="UTC"),
                          lambda: object(), stages=stages, clock=clock)


def _wait_for(predicate, seconds: float = 5.0) -> bool:
    """Poll until `predicate()` is true or the time runs out."""
    deadline = datetime.now() + timedelta(seconds=seconds)
    while datetime.now() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.02)
    return predicate()


def _add_brief(engine, day: str) -> None:
    """Store an empty brief for `day`."""
    with Session(engine) as session:
        session.add(RadarBrief(day=day, doc=dumps({})))
        session.commit()


def test_every_job_runs_however_late_it_is(tmp_path) -> None:
    """A job missed while the PC slept still runs on wake: no misfire grace limit, coalesced."""
    engine = make_engine(tmp_path)
    calls: list[str] = []
    scheduler = _scheduler(engine, calls, settings=make_settings(slack_bot_token="xoxb-test"))
    try:
        scheduler.start()
        for job in scheduler._scheduler.get_jobs():
            assert job.misfire_grace_time is None and job.coalesce is True, job.id
        # Simulate waking up three hours after the brief time.
        past = datetime.now(UTC) - timedelta(hours=3)
        scheduler._scheduler.modify_job(BRIEF_JOB, next_run_time=past)
        assert _wait_for(lambda: "compose" in calls)
    finally:
        scheduler.stop()
        engine.dispose()


def test_catch_up_is_a_recurring_check(tmp_path) -> None:
    """The catch-up check repeats every 30 minutes instead of running once after start."""
    engine = make_engine(tmp_path)
    scheduler = _scheduler(engine, [])
    try:
        scheduler.start()
        job = scheduler._scheduler.get_job(CATCHUP_JOB)
        assert job.trigger.interval == timedelta(minutes=30)
    finally:
        scheduler.stop()
        engine.dispose()


def test_a_brief_skipped_because_of_a_busy_cycle_is_recorded_and_retried(tmp_path, monkeypatch):
    """The daily brief gives up on a cycle that never ends, says so in status, and the next
    catch-up check composes the missing brief."""
    from spyglass_service.radar import scheduler as module

    monkeypatch.setattr(module, "BRIEF_WAIT_SECONDS", 0.2)
    engine = make_engine(tmp_path)
    calls: list[str] = []
    clock = Clock(datetime(2026, 11, 12, 6, 30, tzinfo=UTC))
    scheduler = _scheduler(engine, calls, clock)
    try:
        scheduler._cycle_lock.acquire()
        scheduler._daily_brief()
        last = scheduler.status()["last_brief"]
        assert last["result"] == "skipped" and last["day"] == "2026-11-12" and last["reason"]
        assert calls == []
        scheduler._cycle_lock.release()
        clock.now = datetime(2026, 11, 12, 7, 0, tzinfo=UTC)
        assert scheduler.catchup() is True
        assert calls[-1] == "compose"
        assert scheduler.status()["last_brief"]["result"] == "ok"
    finally:
        engine.dispose()


def test_catch_up_uses_the_simulated_clock_and_skips_before_brief_time(tmp_path) -> None:
    """Before the brief time nothing runs; after it a missing brief is composed; once the
    brief exists the check does nothing."""
    engine = make_engine(tmp_path)
    calls: list[str] = []
    clock = Clock(datetime(2026, 11, 12, 6, 0, tzinfo=UTC))
    scheduler = _scheduler(engine, calls, clock)
    try:
        assert scheduler.catchup() is False and calls == []
        clock.now = datetime(2026, 11, 12, 9, 15, tzinfo=UTC)
        assert scheduler.catchup() is True and calls[-1] == "compose"
        _add_brief(engine, "2026-11-12")
        calls.clear()
        assert scheduler.catchup() is False and calls == []
        assert scheduler.status()["last_check"]["result"] == "brief exists"
    finally:
        engine.dispose()


def test_the_brief_day_is_fixed_when_the_job_fires(tmp_path) -> None:
    """A late brief whose cycle runs past midnight is still the brief of the day it fired."""
    engine = make_engine(tmp_path)
    clock = Clock(datetime(2026, 11, 12, 23, 50, tzinfo=UTC))
    seen: list[str | None] = []
    holder: dict = {}

    def slow_pipeline():
        clock.now = datetime(2026, 11, 13, 0, 20, tzinfo=UTC)  # the cycle crosses midnight
        return {"triaged": 1}

    scheduler = _scheduler(engine, [], clock, settings=make_settings(radar_timezone="UTC",
                                                                       radar_brief_time="23:50"),
                           pipeline=slow_pipeline,
                           compose=lambda: seen.append(holder["s"].brief_day))
    holder["s"] = scheduler
    try:
        scheduler._daily_brief()
        assert seen == ["2026-11-12"]
    finally:
        engine.dispose()


def test_changed_brief_time_and_zone_are_applied_at_the_next_check(tmp_path) -> None:
    """Settings changed while running move the daily job at the next catch-up check."""
    engine = make_engine(tmp_path)
    settings = make_settings(radar_timezone="UTC", radar_brief_time="06:30")
    clock = Clock(datetime(2026, 11, 12, 5, 0, tzinfo=UTC))
    scheduler = _scheduler(engine, [], clock, settings=settings)
    try:
        scheduler.start()
        settings.radar_brief_time = "08:15"
        settings.radar_timezone = "Asia/Tokyo"
        scheduler.catchup()
        trigger = scheduler._scheduler.get_job(BRIEF_JOB).trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert (fields["hour"], fields["minute"]) == ("8", "15")
        assert str(trigger.timezone) == "Asia/Tokyo"
        status = scheduler.status()
        assert status["brief_time"] == "08:15" and status["timezone"] == "Asia/Tokyo"
    finally:
        scheduler.stop()
        engine.dispose()


def test_a_pipeline_that_reached_no_model_makes_the_cycle_an_error_with_a_reason(tmp_path):
    """A full-day outage is not reported as a successful cycle."""
    engine = make_engine(tmp_path)
    outage = {"triaged": 0, "digested": 0, "failed": 217, "unreachable": 217, "skipped": 0,
              "stopped": False}
    scheduler = _scheduler(engine, [], pipeline=lambda: outage)
    try:
        result = scheduler.run_cycle("test")
        stage = result["stages"]["pipeline"]
        assert stage["ok"] is False and stage["status"] == "error"
        assert "217" in stage["reason"] and "could not be reached" in stage["reason"]
        assert result["result"] == "partial" and "pipeline" in result["failed_stages"]
    finally:
        engine.dispose()


def test_a_pipeline_with_some_failures_is_partial(tmp_path) -> None:
    """Some items judged and some not makes the stage partial, with a reason."""
    engine = make_engine(tmp_path)
    counts = {"triaged": 40, "digested": 3, "failed": 5, "unreachable": 5, "skipped": 0,
              "stopped": False}
    scheduler = _scheduler(engine, [], pipeline=lambda: counts)
    try:
        stage = scheduler.run_cycle("test")["stages"]["pipeline"]
        assert stage["status"] == "partial" and "5" in stage["reason"]
    finally:
        engine.dispose()


def test_stop_ends_a_running_cycle_between_stages_within_the_wait(tmp_path) -> None:
    """stop() sets the flag, the cycle ends at the next stage boundary and stop returns."""
    engine = make_engine(tmp_path)
    calls: list[str] = []
    started = threading.Event()
    holder: dict = {}

    def legacy():
        started.set()
        holder["s"]._stop_event.wait(5)  # a stage that notices the stop request
        calls.append("legacy")

    scheduler = _scheduler(engine, calls, legacy=legacy)
    holder["s"] = scheduler
    try:
        assert scheduler.start_cycle_in_background("manual")
        assert started.wait(5)
        assert scheduler.stop(wait_seconds=5) is True
        assert calls == ["legacy"]  # no stage after the stop request ran
        last = scheduler.status()["last_cycle"]
        assert last["result"] == "stopped"
    finally:
        engine.dispose()


def test_stop_waits_only_a_bounded_time_for_a_stuck_stage(tmp_path) -> None:
    """A stage that ignores the flag does not hold stop() beyond its wait."""
    engine = make_engine(tmp_path)
    release = threading.Event()
    started = threading.Event()

    def stuck():
        started.set()
        release.wait(10)

    scheduler = _scheduler(engine, [], legacy=stuck)
    try:
        assert scheduler.start_cycle_in_background("manual")
        assert started.wait(5)
        before = datetime.now()
        assert scheduler.stop(wait_seconds=0.3) is False
        assert datetime.now() - before < timedelta(seconds=3)
    finally:
        release.set()
        _wait_for(lambda: not scheduler.running)
        engine.dispose()


def test_a_capture_during_a_cycle_is_assessed_right_after_it(tmp_path) -> None:
    """A kick that finds a cycle running is remembered and runs embed and pipeline after it."""
    engine = make_engine(tmp_path)
    calls: list[str] = []
    started, release = threading.Event(), threading.Event()

    def slow_watch():
        started.set()
        release.wait(5)
        calls.append("watch")

    scheduler = _scheduler(engine, calls, watch=slow_watch)
    try:
        assert scheduler.start_cycle_in_background("manual")
        assert started.wait(5)
        assert scheduler.kick_assessment() is False
        assert scheduler.status()["kick_pending"] is True
        release.set()
        assert _wait_for(lambda: calls[-2:] == ["embed", "pipeline"] and not scheduler.running
                         and calls.count("pipeline") == 2)
        assert scheduler.status()["kick_pending"] is False
    finally:
        engine.dispose()


def test_brief_exists_reports_whether_a_day_has_a_brief(tmp_path) -> None:
    """The helper the catch-up check uses answers per day."""
    from datetime import date

    from spyglass_service.radar.scheduler_support import brief_exists

    engine = make_engine(tmp_path)
    _add_brief(engine, "2026-03-04")
    assert brief_exists(engine, date(2026, 3, 4)) is True
    assert brief_exists(engine, date(2026, 3, 5)) is False
    engine.dispose()
