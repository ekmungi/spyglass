"""Tests for when a background filing run starts by itself (radar/filing_trigger.py)."""

import json
import os
from datetime import UTC, datetime, time as dtime, timedelta

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_queue, filing_status
from spyglass_service.radar import filing_trigger as ft

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
QUIET = timedelta(minutes=10)


def decide(**changes):
    """`decide` with a due-by-quiet default; keyword changes override it."""
    args = {"mode": "auto", "has_work": True, "activity": NOW - timedelta(minutes=11),
            "quiet": QUIET, "daily": dtime(21, 0), "last_started": None, "next_retry": None,
            "running": False, "busy": False, "zone": UTC, **changes}
    return ft.decide(NOW, **args)


def test_a_quiet_queue_with_work_starts_a_run():
    assert decide() == "quiet"
    assert decide(activity=None) == "quiet"


@pytest.mark.parametrize("changes", [
    {"mode": "off"}, {"has_work": False}, {"running": True}, {"busy": True},
    {"activity": NOW - timedelta(minutes=9)}, {"next_retry": NOW + timedelta(minutes=1)},
])
def test_nothing_starts_when_a_rule_says_no(changes):
    assert decide(**changes) is None


def test_the_daily_time_starts_a_run_even_without_quiet_once_a_day():
    busy_queue = NOW.replace(hour=21, minute=5) - timedelta(minutes=1)
    at_nine = {"activity": busy_queue, "daily": dtime(21, 0)}
    assert ft.decide(NOW.replace(hour=21, minute=5), **{**_base(), **at_nine}) == "daily"
    ran_after = NOW.replace(hour=21, minute=1)
    assert ft.decide(NOW.replace(hour=21, minute=5),
                     **{**_base(), **at_nine, "last_started": ran_after}) is None


def test_the_daily_time_respects_the_retry_time():
    late = NOW.replace(hour=21, minute=5)
    assert ft.decide(late, **{**_base(), "activity": late, "next_retry": late + timedelta(hours=1)}) is None


def _base() -> dict:
    """Arguments for decide without the clock."""
    return {"mode": "plan_first", "has_work": True, "activity": None, "quiet": QUIET,
            "daily": dtime(21, 0), "last_started": None, "next_retry": None, "running": False,
            "busy": False, "zone": UTC}


def test_settings_are_read_with_safe_fallbacks():
    assert ft.daily_time(Settings(_env_file=None, radar_filing_daily_time="07:45")) == dtime(7, 45)
    assert ft.daily_time(Settings(_env_file=None, radar_filing_daily_time="soon")) == dtime(21, 0)
    assert ft.quiet_minutes(Settings(_env_file=None, radar_filing_quiet_minutes=0)) == 2
    assert ft.quiet_minutes(Settings(_env_file=None, radar_filing_quiet_minutes=999)) == 240


@pytest.fixture(autouse=True)
def background_unlocked(monkeypatch):
    """The developer unlock: without it no background run starts in this version."""
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")


@pytest.fixture
def db(tmp_path):
    """A database with one item."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="e1", title="T", url="https://x.example/1"))
        session.commit()
    yield engine, tmp_path
    engine.dispose()


def test_last_activity_is_the_latest_queuing(db):
    engine, _tmp = db
    assert ft.last_activity(engine) is None
    filing_queue.enqueue(engine, 1)
    assert ft.last_activity(engine) is not None


def test_cycle_busy_reads_the_cycle_lock_file(db):
    _engine, tmp = db
    settings = Settings(_env_file=None, data_dir=tmp / "data")
    assert ft.cycle_busy(settings) is False
    lock = tmp / "data" / ft.CYCLE_LOCK_FILE
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}),
                    encoding="utf-8")
    assert ft.cycle_busy(settings) is True
    lock.write_text(json.dumps({"pid": 999_999_9, "started_at": datetime.now(UTC).isoformat()}),
                    encoding="utf-8")
    assert ft.cycle_busy(settings) is False


def test_the_tick_starts_a_run_only_when_due(db):
    engine, tmp = db
    settings = Settings(_env_file=None, data_dir=tmp / "data", radar_filing_mode="auto",
                        radar_filing_daily_time="23:59", vault_path=tmp, radar_filing_ingest_skill="vault-skills:ingest", radar_filing_manage_skill="vault-skills:manage")
    calls = []

    def runner(*_args):
        calls.append(1)
        return {}

    assert ft.filing_tick(engine, settings, now=NOW, runner=runner, busy=lambda _s: False) is None
    filing_queue.enqueue(engine, 1)
    soon = datetime.now(UTC) + timedelta(minutes=1)
    assert ft.filing_tick(engine, settings, now=soon, runner=runner, busy=lambda _s: False) is None
    later = datetime.now(UTC) + timedelta(minutes=11)
    assert ft.filing_tick(engine, settings, now=later, runner=runner,
                          busy=lambda _s: False) == "quiet"
    assert calls == [1]


def test_the_tick_does_nothing_while_off_or_running(db):
    engine, tmp = db
    filing_queue.enqueue(engine, 1)
    later = datetime.now(UTC) + timedelta(minutes=30)
    off = Settings(_env_file=None, data_dir=tmp / "data")
    assert ft.filing_tick(engine, off, now=later, runner=lambda *_a: {}) is None
    filing_status.begin_run(engine, mode="auto", kind="file", model="m", item_ids=[1],
                            now=later - timedelta(minutes=5))
    on = off.model_copy(update={"radar_filing_mode": "auto"})
    assert ft.filing_tick(engine, on, now=later, runner=lambda *_a: {},
                          busy=lambda _s: False) is None


def test_a_failing_check_is_logged_not_raised(db, caplog):
    engine, tmp = db
    filing_queue.enqueue(engine, 1)
    settings = Settings(_env_file=None, data_dir=tmp / "data", radar_filing_mode="auto",
                        vault_path=tmp, radar_filing_ingest_skill="vault-skills:ingest", radar_filing_manage_skill="vault-skills:manage")

    def broken(*_args):
        raise RuntimeError("boom")

    later = datetime.now(UTC) + timedelta(minutes=30)
    assert ft.filing_tick(engine, settings, now=later, runner=broken, busy=lambda _s: False) is None
    assert "background filing check failed" in caplog.text


def test_the_scheduler_registers_the_filing_check_beside_the_upkeep(tmp_path):
    from spyglass_service.radar.scheduler_extras import FILING_JOB, register_maintenance_jobs

    class FakeScheduler:
        """Collects add_job calls."""

        def __init__(self):
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((kwargs.get("id"), trigger, kwargs))

    scheduler = FakeScheduler()
    settings = Settings(_env_file=None, data_dir=tmp_path)
    register_maintenance_jobs(scheduler, lambda target, name: target, None, settings,
                              lambda _w: True, lambda: None, UTC)
    filing = [job for job in scheduler.jobs if job[0] == FILING_JOB]
    assert filing and filing[0][1] == "interval" and filing[0][2]["minutes"] == ft.TICK_MINUTES
