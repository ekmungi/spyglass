"""The daily database backup: it is scheduled, waits for the cycle lock, and is caught up once.

Covers the job registration, the lock rule (never during a cycle), the stale-backup catch-up
(one backup when the newest is over 26 hours old, none when it is fresh) and the weekly upkeep's
tolerant call to the usage pruning, which another module provides.
"""

import os
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

from spyglass_service.backup import list_backups
from spyglass_service.models import RunLog
from spyglass_service.radar.models import RadarBrief, dumps
from spyglass_service.radar import scheduler_extras as extras
from spyglass_service.radar.scheduler import RadarScheduler

from .test_sources_support import make_engine, make_settings

# The real clock: backups get real file times, so "old" and "fresh" are measured against it.
NOW = datetime.now(UTC).replace(microsecond=0)


def _settings(tmp_path: Path, **overrides):
    """A settings stand-in pointing at tmp_path/spyglass.db (see `_real_db`) and a backups folder."""
    return make_settings(
        db_path=tmp_path / "spyglass.db", backups_dir=tmp_path / "backups", backup_keep=5,
        data_dir=None, radar_timezone="UTC", **overrides)


def _real_db(tmp_path: Path):
    """A migrated database in tmp_path/spyglass.db and the engine over it."""
    from spyglass_service.db import create_db_engine, init_db

    engine = create_db_engine(tmp_path / "spyglass.db")
    init_db(engine)
    return engine


def _age(path: Path, hours: float) -> None:
    """Make a backup file look `hours` old relative to NOW."""
    stamp = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))


def test_the_daily_backup_job_is_registered_at_the_quiet_hour(tmp_path) -> None:
    """start() registers a daily job at the configured time, 03:00 by default."""
    engine = make_engine(tmp_path)
    try:
        scheduler = RadarScheduler(engine, make_settings(radar_timezone="UTC"), lambda: None)
        scheduler.start()
        try:
            job = scheduler._scheduler.get_job(extras.BACKUP_JOB)
            assert job is not None
            fields = {f.name: str(f) for f in job.trigger.fields}
            assert fields["hour"] == "3" and fields["minute"] == "0"
            assert scheduler._scheduler.get_job(extras.UPKEEP_JOB) is not None
        finally:
            scheduler.stop(wait_seconds=1)
    finally:
        engine.dispose()


def test_the_backup_time_is_read_from_settings_with_a_safe_fallback() -> None:
    """A valid time is used; an unreadable one falls back to 03:00."""
    assert extras.backup_time(SimpleNamespace(radar_backup_time="04:15")).hour == 4
    assert extras.backup_time(SimpleNamespace(radar_backup_time="soon")).hour == 3
    assert extras.backup_time(SimpleNamespace()).hour == 3


def test_a_cycle_holding_the_lock_postpones_the_backup(tmp_path) -> None:
    """If the lock cannot be taken, nothing is written and nothing is released."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        released: list[int] = []
        result = extras.daily_backup(engine, settings, lambda _w: False, lambda: released.append(1))
        assert result is None and released == []
        assert list_backups(settings.backups_dir) == []
    finally:
        engine.dispose()


def test_the_daily_backup_runs_under_the_lock_and_logs_it(tmp_path) -> None:
    """The backup is taken between acquire and release, and a RunLog row records it."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        events: list[str] = []

        def acquire(_wait: float) -> bool:
            events.append("acquire")
            return True

        path = extras.daily_backup(engine, settings, acquire, lambda: events.append("release"))
        assert path is not None and path.exists()
        assert events == ["acquire", "release"]
        with Session(engine) as session:
            row = session.exec(select(RunLog).where(RunLog.source == "backup")).one()
        assert row.status == "ok"
    finally:
        engine.dispose()


def test_a_low_disk_skips_the_backup_with_a_logged_reason(tmp_path, monkeypatch) -> None:
    """Too little free space is a skipped run with a plain sentence, not an error."""
    from spyglass_service import backup as backup_mod

    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        folder = Path(settings.backups_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "spyglass-20260101-030000.db").write_bytes(b"x" * 100)
        monkeypatch.setattr(backup_mod, "_free_bytes", lambda _folder: 10)
        released: list[int] = []
        assert extras.daily_backup(engine, settings, lambda _w: True,
                                   lambda: released.append(1)) is None
        assert released == [1]
        with Session(engine) as session:
            row = session.exec(select(RunLog).where(RunLog.source == "backup")).one()
        assert row.status == "skipped" and "disk" in (row.detail or "").lower()
    finally:
        engine.dispose()


def test_a_failed_backup_is_logged_and_the_lock_is_released(tmp_path, monkeypatch) -> None:
    """An error in the copy never escapes and never keeps the lock."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        released: list[int] = []

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(extras, "backup_db", boom)
        assert extras.daily_backup(engine, settings, lambda _w: True,
                                   lambda: released.append(1)) is None
        assert released == [1]
        with Session(engine) as session:
            row = session.exec(select(RunLog).where(RunLog.source == "backup")).one()
        assert row.status == "error" and "disk full" in row.detail
    finally:
        engine.dispose()


def test_catch_up_takes_one_backup_when_the_newest_is_stale(tmp_path) -> None:
    """A newest backup over 26 hours old triggers exactly one backup; the next check finds it fresh."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        old = extras.daily_backup(engine, settings, lambda _w: True, lambda: None)
        _age(old, 30)
        taken = [extras.backup_catchup(engine, settings, lambda _w: True, lambda: None, NOW)
                 for _ in range(2)]
        assert taken == [True, False]
        assert len(list_backups(settings.backups_dir)) == 2
    finally:
        engine.dispose()


def test_catch_up_leaves_a_fresh_backup_alone(tmp_path) -> None:
    """A backup from 3 hours ago is recent enough."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        path = extras.daily_backup(engine, settings, lambda _w: True, lambda: None)
        _age(path, 3)
        assert extras.backup_catchup(engine, settings, lambda _w: True, lambda: None, NOW) is False
        assert len(list_backups(settings.backups_dir)) == 1
    finally:
        engine.dispose()


def test_catch_up_waits_while_a_cycle_runs(tmp_path) -> None:
    """With the lock taken the catch-up does nothing now; the next 30-minute check retries."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        assert extras.backup_catchup(engine, settings, lambda _w: False, lambda: None, NOW) is False
        assert list_backups(settings.backups_dir) == []
    finally:
        engine.dispose()


def test_catch_up_does_nothing_without_a_database(tmp_path) -> None:
    """Settings without a database path (or a missing file) are not an error."""
    engine = make_engine(tmp_path)
    try:
        assert extras.backup_catchup(engine, make_settings(), lambda _w: True, lambda: None,
                                     NOW) is False
        missing = make_settings(db_path=tmp_path / "none.db", backups_dir=tmp_path / "b",
                                backup_keep=5)
        assert extras.backup_catchup(engine, missing, lambda _w: True, lambda: None, NOW) is False
    finally:
        engine.dispose()


def test_scheduler_catchup_runs_the_backup_catch_up(tmp_path) -> None:
    """RadarScheduler.catchup() calls the backup catch-up with its own lock."""
    engine = _real_db(tmp_path)
    try:
        settings = _settings(tmp_path)
        with Session(engine) as session:  # today's brief exists, so no cycle is started
            session.add(RadarBrief(day=NOW.date().isoformat(), doc=dumps({})))
            session.commit()
        scheduler = RadarScheduler(engine, settings, lambda: None, clock=lambda: NOW)
        scheduler.catchup()
        assert len(list_backups(settings.backups_dir)) == 1
        scheduler.catchup()
        assert len(list_backups(settings.backups_dir)) == 1
    finally:
        engine.dispose()


def test_weekly_upkeep_prunes_usage_when_that_module_exists(tmp_path, monkeypatch) -> None:
    """prune_usage is called once, lazily, after the housekeeping steps."""
    engine = make_engine(tmp_path)
    try:
        calls: list[tuple] = []
        module = types.ModuleType("spyglass_service.radar.usage")
        module.prune_usage = lambda eng, days: calls.append((eng, days)) or 2
        monkeypatch.setitem(sys.modules, "spyglass_service.radar.usage", module)
        monkeypatch.setattr("spyglass_service.radar.housekeeping.run_housekeeping",
                            lambda *_a, **_k: {"ok": True})
        report = extras.weekly_upkeep(engine, make_settings(), lambda _w: True, lambda: None)
        assert calls == [(engine, 180)] and report["usage"] == {"deleted": 2}
    finally:
        engine.dispose()


def test_weekly_upkeep_tolerates_a_missing_or_failing_usage_module(tmp_path, monkeypatch) -> None:
    """No module, or a module that raises, never fails the upkeep."""
    engine = make_engine(tmp_path)
    try:
        monkeypatch.setattr("spyglass_service.radar.housekeeping.run_housekeeping",
                            lambda *_a, **_k: {"ok": True})
        monkeypatch.setitem(sys.modules, "spyglass_service.radar.usage", None)  # import fails
        assert extras.weekly_upkeep(engine, make_settings(), lambda _w: True,
                                    lambda: None)["ok"] is True
        module = types.ModuleType("spyglass_service.radar.usage")

        def broken(*_a, **_k):
            raise RuntimeError("bad table")

        module.prune_usage = broken
        monkeypatch.setitem(sys.modules, "spyglass_service.radar.usage", module)
        report = extras.weekly_upkeep(engine, make_settings(), lambda _w: True, lambda: None)
        assert report["ok"] is True and "error" in report["usage"]
    finally:
        engine.dispose()


def test_weekly_upkeep_works_with_the_real_usage_module(tmp_path, monkeypatch) -> None:
    """The real prune_usage accepts the call the upkeep makes (an empty table deletes nothing)."""
    engine = make_engine(tmp_path)
    try:
        monkeypatch.setattr("spyglass_service.radar.housekeeping.run_housekeeping",
                            lambda *_a, **_k: {"ok": True})
        report = extras.weekly_upkeep(engine, make_settings(), lambda _w: True, lambda: None)
        assert report["usage"] == {"deleted": 0}
    finally:
        engine.dispose()
