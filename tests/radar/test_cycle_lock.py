"""Regression tests: two service processes never run a cycle at the same time."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from spyglass_service.radar.cycle_lock import CycleFileLock
from spyglass_service.radar.scheduler import RadarScheduler

from .test_sources_support import make_engine, make_settings

OTHER_PID = 424242


def _write_holder(path, pid: int, started: datetime) -> None:
    """Write a lock file as another process would."""
    path.write_text(json.dumps({"pid": pid, "started_at": started.isoformat()}), encoding="utf-8")


def test_lock_is_exclusive_and_records_pid_and_start_time(tmp_path) -> None:
    """The first holder wins; a second holder is refused until the first releases."""
    path = tmp_path / "cycle.lock"
    first = CycleFileLock(path, pid_alive=lambda _pid: True)
    second = CycleFileLock(path, pid_alive=lambda _pid: True, pid=OTHER_PID)
    assert first.acquire() is True
    holder = json.loads(path.read_text(encoding="utf-8"))
    assert holder["pid"] == os.getpid() and holder["started_at"]
    assert second.acquire() is False
    first.release()
    assert not path.exists()
    assert second.acquire() is True
    second.release()


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path) -> None:
    """A crashed service leaves its lock behind; the next one takes it over."""
    path = tmp_path / "cycle.lock"
    _write_holder(path, OTHER_PID, datetime.now(UTC))
    lock = CycleFileLock(path, pid_alive=lambda pid: pid != OTHER_PID)
    assert lock.acquire() is True
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid()
    lock.release()


def test_a_live_holder_is_respected_but_a_very_old_lock_is_not(tmp_path) -> None:
    """A live process keeps its lock; a lock far older than any cycle is stale (pid reuse)."""
    path = tmp_path / "cycle.lock"
    _write_holder(path, OTHER_PID, datetime.now(UTC))
    assert CycleFileLock(path, pid_alive=lambda _pid: True).acquire() is False
    _write_holder(path, OTHER_PID, datetime.now(UTC) - timedelta(days=2))
    lock = CycleFileLock(path, pid_alive=lambda _pid: True)
    assert lock.acquire() is True
    lock.release()


def test_lock_with_no_max_age_is_not_stale_after_twelve_hours(tmp_path) -> None:
    """The desktop app holds its lock as long as it stays open, so only a dead holder may make
    it stale, however old the lock is."""
    path = tmp_path / "desktop.lock"
    _write_holder(path, OTHER_PID, datetime.now(UTC) - timedelta(days=2))
    assert CycleFileLock(path, pid_alive=lambda _pid: True, max_age=None).acquire() is False
    assert CycleFileLock(path, pid_alive=lambda _pid: False, max_age=None).acquire() is True


LOCKED_AT = datetime(2026, 11, 14, 8, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(("born", "taken"), [
    (LOCKED_AT + timedelta(minutes=5), True),    # created after the lock: a reused pid
    (LOCKED_AT + timedelta(seconds=3), True),    # past the rounding tolerance
    (LOCKED_AT + timedelta(seconds=1), False),   # within the tolerance: the real holder
    (LOCKED_AT - timedelta(seconds=4), False),   # created before it wrote the lock
    (None, False),                               # unknown: never guess a takeover
])
def test_a_live_pid_is_judged_by_when_its_process_started(tmp_path, born, taken) -> None:
    """Windows reuses pids. The real holder's process existed before it wrote the lock; a process
    created after that holds the pid by chance, so the lock is stale and taken at once."""
    path = tmp_path / "desktop.lock"
    _write_holder(path, OTHER_PID, LOCKED_AT)
    asked: list[int] = []

    def started_at(pid: int):
        asked.append(pid)
        return born

    lock = CycleFileLock(path, pid_alive=lambda _pid: True, max_age=None,
                         pid_started_at=started_at)
    assert lock.acquire() is taken
    assert asked and set(asked) == {OTHER_PID}
    holder = json.loads(path.read_text(encoding="utf-8"))
    assert (holder["pid"] == os.getpid()) is taken


def test_the_cycle_lock_keeps_its_age_rule_and_ignores_process_start(tmp_path) -> None:
    """Only the desktop lock (no age limit) asks when the holder started; existing callers keep
    their behaviour."""
    path = tmp_path / "cycle.lock"
    _write_holder(path, OTHER_PID, datetime.now(UTC) - timedelta(hours=1))
    lock = CycleFileLock(path, pid_alive=lambda _pid: True,
                         pid_started_at=lambda _pid: datetime.now(UTC))
    assert lock.acquire() is False


def test_an_unreadable_fresh_lock_counts_as_held(tmp_path) -> None:
    """A lock file being written by another process right now is not stolen."""
    path = tmp_path / "cycle.lock"
    path.write_text("", encoding="utf-8")
    assert CycleFileLock(path, pid_alive=lambda _pid: True).acquire() is False


def test_the_real_liveness_check_sees_this_process() -> None:
    """The default check reports the running process as alive and a free pid as dead."""
    from spyglass_service.radar.cycle_lock import pid_alive

    assert pid_alive(os.getpid()) is True
    assert pid_alive(2**31 - 3) is False


def test_a_second_process_scheduler_does_not_run_a_cycle(tmp_path) -> None:
    """With another live process holding the data directory's lock, a cycle is refused."""
    engine = make_engine(tmp_path)
    try:
        settings = make_settings(data_dir=tmp_path)
        calls: list[str] = []
        names = ("legacy", "radar", "raindrop", "embed", "pipeline", "watch", "compose")
        stages = {n: (lambda n=n: calls.append(n)) for n in names}
        scheduler = RadarScheduler(engine, settings, lambda: object(), stages=stages,
                                   pid_alive=lambda _pid: True)
        _write_holder(scheduler.lock_path, OTHER_PID, datetime.now(UTC))
        assert scheduler.run_cycle("test") == {"result": "busy", "trigger": "test"}
        assert calls == [] and not scheduler.running
        assert scheduler.kick_assessment() is False
        scheduler._kick_pending.clear()  # the other process will judge the items
        scheduler.lock_path.unlink()
        assert scheduler.run_cycle("test")["result"] == "ok"
        assert calls[0] == "legacy" and not scheduler.lock_path.exists()
    finally:
        engine.dispose()
