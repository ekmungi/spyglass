"""Regression tests: two service processes never run a cycle at the same time."""

import json
import os
from datetime import UTC, datetime, timedelta

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
