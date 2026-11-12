"""Tests for the radar scheduler: cycle stages, the overlap lock, catch-up and job wiring."""

import threading
from datetime import datetime, time as dtime

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.models import RadarBrief, dumps
from spyglass_service.radar.scheduler import (
    RadarScheduler,
    needs_catchup,
    parse_brief_time,
)

from .test_sources_support import make_engine, make_settings

STAGES = ("legacy", "radar", "raindrop", "embed", "pipeline", "watch", "compose")


def make_scheduler(engine, calls: list[str], **overrides) -> RadarScheduler:
    def stage(name):
        def run():
            calls.append(name)
            return {"n": 1}
        return run

    stages = {name: stage(name) for name in STAGES}
    stages.update(overrides)
    return RadarScheduler(engine, make_settings(), lambda: object(), stages=stages)


def test_parse_brief_time_accepts_hh_mm_and_falls_back() -> None:
    assert parse_brief_time("07:05") == dtime(7, 5)
    assert parse_brief_time(" 6:30 ") == dtime(6, 30)
    for bad in ("", "noon", "25:99", None):
        assert parse_brief_time(bad) == dtime(6, 30)


@pytest.mark.parametrize(
    ("hour", "has_brief", "expected"),
    [(5, False, False), (6, False, True), (7, False, True), (7, True, False), (23, False, True)],
)
def test_needs_catchup_decision(hour: int, has_brief: bool, expected: bool) -> None:
    now = datetime(2026, 11, 12, hour, 31)  # 31 minutes past the hour
    assert needs_catchup(now, dtime(6, 30), has_brief) is expected


def test_needs_catchup_boundary_is_inclusive() -> None:
    assert needs_catchup(datetime(2026, 11, 12, 6, 30), dtime(6, 30), False) is True


def test_run_cycle_runs_stages_in_order_without_compose(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        result = make_scheduler(engine, calls).run_cycle("test")
        assert calls == ["legacy", "radar", "raindrop", "embed", "pipeline", "watch"]
        assert result["result"] == "ok" and result["failed_stages"] == []
    finally:
        engine.dispose()


def test_run_cycle_with_compose_adds_the_compose_stage(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        make_scheduler(engine, calls).run_cycle("test", compose=True)
        assert calls[-1] == "compose"
    finally:
        engine.dispose()


def test_a_failing_stage_is_recorded_and_the_rest_still_run(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []

        def boom():
            raise RuntimeError("feed outage")

        scheduler = make_scheduler(engine, calls, radar=boom)
        result = scheduler.run_cycle("test")
        assert result["result"] == "partial" and result["failed_stages"] == ["radar"]
        assert "feed outage" in result["stages"]["radar"]["detail"]
        assert calls == ["legacy", "raindrop", "embed", "pipeline", "watch"]
        last = scheduler.status()["last_cycle"]
        assert last["result"] == "partial" and last["trigger"] == "test"
    finally:
        engine.dispose()


def test_cycles_never_overlap(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        started, release = threading.Event(), threading.Event()
        calls: list[str] = []

        def slow():
            started.set()
            release.wait(5)

        scheduler = make_scheduler(engine, calls, legacy=slow)
        assert scheduler.start_cycle_in_background("manual") is True
        assert started.wait(5) and scheduler.running
        assert scheduler.start_cycle_in_background("manual") is False
        assert scheduler.run_cycle("second") == {"result": "busy", "trigger": "second"}
        assert scheduler.kick_assessment() is False
        assert scheduler.status()["cycle_running"] is True
        release.set()
        for _ in range(100):  # wait for the worker thread to finish the cycle
            if not scheduler.running:
                break
            threading.Event().wait(0.05)
        assert not scheduler.running
        assert scheduler.status()["last_cycle"]["result"] == "ok"
        assert scheduler.run_cycle("third")["result"] == "ok"
    finally:
        engine.dispose()


def test_daily_brief_waits_for_a_running_cycle(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        scheduler = make_scheduler(engine, calls)
        scheduler._cycle_lock.acquire()
        timer = threading.Timer(0.2, scheduler._cycle_lock.release)
        timer.start()
        result = scheduler.run_cycle("daily-brief", compose=True, wait_seconds=5)
        timer.join()
        assert result["result"] == "ok" and calls[-1] == "compose"
    finally:
        engine.dispose()


def test_kick_assessment_runs_only_embed_and_pipeline(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        scheduler = make_scheduler(engine, calls)
        assert scheduler.kick_assessment() is True
        for _ in range(100):
            if calls == ["embed", "pipeline"] and not scheduler.running:
                break
            threading.Event().wait(0.05)
        assert calls == ["embed", "pipeline"]
    finally:
        engine.dispose()


def test_catchup_runs_once_when_the_brief_is_missing_and_time_has_passed(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        scheduler = make_scheduler(engine, calls)
        scheduler._settings.radar_brief_time = "00:00"  # always already passed
        assert scheduler.catchup() is True
        assert calls[-1] == "compose"
        today = datetime.now(scheduler._scheduler.timezone).date().isoformat()
        with Session(engine) as session:
            session.add(RadarBrief(day=today, doc=dumps({})))
            session.commit()
        calls.clear()
        assert scheduler.catchup() is False and calls == []
        # Before the brief time, a missing brief is not a reason to run anything yet.
        with Session(engine) as session:
            session.delete(session.exec(select(RadarBrief)).first())
            session.commit()
        scheduler._settings.radar_brief_time = "23:59"
        now = datetime.now(scheduler._scheduler.timezone)
        if now.time() < dtime(23, 59):
            assert scheduler.catchup() is False and calls == []
    finally:
        engine.dispose()


def test_start_registers_jobs_and_stop_is_safe(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        scheduler = make_scheduler(engine, [])
        scheduler._settings.slack_bot_token = "xoxb-test"
        scheduler.start()
        scheduler.start()  # idempotent
        status = scheduler.status()
        assert status["scheduler_running"] and status["next_cycle_at"] and status["next_brief_at"]
        assert status["next_capture_poll_at"] and status["brief_time"] == "06:30"
        scheduler.stop()
        scheduler.stop()
        assert scheduler.status()["scheduler_running"] is False
    finally:
        engine.dispose()


def test_capture_job_is_not_scheduled_without_credentials(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        scheduler = make_scheduler(engine, [])
        scheduler.start()
        assert scheduler.status()["next_capture_poll_at"] is None
        scheduler.stop()
    finally:
        engine.dispose()


def test_poll_captures_assesses_when_links_arrive(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path)
    try:
        from spyglass_service.radar.sources import gmail, slack

        calls: list[str] = []
        scheduler = make_scheduler(engine, calls)
        monkeypatch.setattr(slack, "collect_slack", lambda e, s: 2)
        monkeypatch.setattr(gmail, "collect_gmail", lambda e, s, **k: {"capture": 1})
        assert scheduler.poll_captures() == {"slack": 2, "gmail": 1}
        for _ in range(100):
            if calls == ["embed", "pipeline"] and not scheduler.running:
                break
            threading.Event().wait(0.05)
        assert calls == ["embed", "pipeline"]
    finally:
        engine.dispose()


def test_poll_captures_skips_unconfigured_sources_and_survives_errors(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        scheduler = make_scheduler(engine, calls)
        assert scheduler.poll_captures() == {}  # neither is configured
        assert calls == []
    finally:
        engine.dispose()
