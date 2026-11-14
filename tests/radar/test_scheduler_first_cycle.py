"""The first collection after opening: soon when the last one is stale, never twice at once.

Opening Spyglass used to wait a full interval before the first collection, so a PC opened after
a long break showed old items for two hours. The finish time of the last cycle is kept in the
data folder so a restart can tell a fresh collection from a stale one.
"""

import json
from datetime import UTC, datetime, timedelta

from spyglass_service.radar.scheduler import (
    CYCLE_JOB,
    LAST_CYCLE_FILE,
    RadarScheduler,
    first_cycle_at,
)

from .test_scheduler_catchup import STAGES, Clock, _scheduler
from .test_sources_support import make_engine, make_settings

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
INTERVAL = timedelta(hours=2)


def test_first_cycle_soon_when_last_is_older_than_the_interval() -> None:
    """A collection older than the interval is repeated a minute after opening."""
    assert first_cycle_at(NOW, NOW - timedelta(hours=3), INTERVAL) == NOW + timedelta(seconds=60)


def test_first_cycle_soon_when_never_collected() -> None:
    """With no recorded collection the first one runs a minute after opening."""
    assert first_cycle_at(NOW, None, INTERVAL) == NOW + timedelta(seconds=60)


def test_first_cycle_waits_for_the_interval_after_a_recent_one() -> None:
    """A recent collection keeps the normal rhythm: its finish time plus the interval."""
    assert first_cycle_at(NOW, NOW - timedelta(minutes=30), INTERVAL) == NOW + timedelta(minutes=90)


def test_a_finished_cycle_is_persisted(tmp_path) -> None:
    """The end of a cycle writes its finish time, which a new scheduler reads back."""
    engine = make_engine(tmp_path)
    settings = make_settings(radar_timezone="UTC", data_dir=tmp_path)
    clock = Clock(NOW)
    try:
        scheduler = _scheduler(engine, [], clock=clock, settings=settings)
        assert scheduler.last_finished() is None
        scheduler.run_cycle("manual")
        stored = json.loads((tmp_path / LAST_CYCLE_FILE).read_text(encoding="utf-8"))
        written = datetime.fromisoformat(stored["finished_at"])
        assert written.tzinfo is not None
        again = _scheduler(engine, [], clock=clock, settings=settings)
        assert again.last_finished() == written
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        engine.dispose()


def test_an_unreadable_file_means_unknown(tmp_path) -> None:
    """A damaged or malformed file is treated as no recorded collection."""
    engine = make_engine(tmp_path)
    settings = make_settings(radar_timezone="UTC", data_dir=tmp_path)
    try:
        scheduler = _scheduler(engine, [], settings=settings)
        for text in ("{not json", '{"finished_at": "yesterday"}', "[]", '{"other": 1}'):
            (tmp_path / LAST_CYCLE_FILE).write_text(text, encoding="utf-8")
            assert scheduler.last_finished() is None, text
    finally:
        engine.dispose()


def test_scheduled_cycle_skips_after_a_recent_catch_up(tmp_path) -> None:
    """A cycle that finished within the interval (for example the catch-up one) is not repeated."""
    engine = make_engine(tmp_path)
    settings = make_settings(radar_timezone="UTC", data_dir=tmp_path)
    calls: list[str] = []
    try:
        scheduler = _scheduler(engine, calls, clock=Clock(NOW), settings=settings)
        (tmp_path / LAST_CYCLE_FILE).write_text(
            json.dumps({"finished_at": (NOW - timedelta(minutes=10)).isoformat()}), encoding="utf-8")
        scheduler._scheduled_cycle()
        assert calls == []
    finally:
        engine.dispose()


def test_scheduled_cycle_runs_when_the_last_one_is_stale(tmp_path) -> None:
    """A collection older than the interval does not stop the scheduled cycle."""
    engine = make_engine(tmp_path)
    settings = make_settings(radar_timezone="UTC", data_dir=tmp_path)
    calls: list[str] = []
    try:
        scheduler = _scheduler(engine, calls, clock=Clock(NOW), settings=settings)
        (tmp_path / LAST_CYCLE_FILE).write_text(
            json.dumps({"finished_at": (NOW - timedelta(hours=3)).isoformat()}), encoding="utf-8")
        scheduler._scheduled_cycle()
        assert "legacy" in calls and "watch" in calls and set(calls) <= set(STAGES)
    finally:
        engine.dispose()


def test_start_schedules_the_first_cycle_from_the_last_finish(tmp_path) -> None:
    """The interval job's first run is a minute away when stale, else after the interval."""
    engine = make_engine(tmp_path)
    try:
        for age, soon in ((timedelta(hours=5), True), (timedelta(minutes=20), False)):
            data = tmp_path / ("stale" if soon else "fresh")
            data.mkdir()
            finished = datetime.now(UTC) - age
            (data / LAST_CYCLE_FILE).write_text(
                json.dumps({"finished_at": finished.isoformat()}), encoding="utf-8")
            scheduler: RadarScheduler = _scheduler(
                engine, [], settings=make_settings(radar_timezone="UTC", data_dir=data))
            try:
                scheduler.start()
                due = scheduler._scheduler.get_job(CYCLE_JOB).next_run_time
                wait = (due - datetime.now(UTC)).total_seconds()
                if soon:
                    assert 50 < wait <= 60
                else:
                    assert abs(wait - (INTERVAL - age).total_seconds()) < 30
            finally:
                scheduler.stop()
    finally:
        engine.dispose()
