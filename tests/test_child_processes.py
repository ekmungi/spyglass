"""The registry of child processes the service starts on its own, which a stop ends all at once.

Most tests use stand-in processes and a recording kill; two start a real, short Python process
to show that the real kill ends it and that an already-exited process is left alone.
"""

import subprocess
import sys
import threading
import time

from spyglass_service import child_processes
from spyglass_service.child_processes import ChildRegistry


class FakeProc:
    """A stand-in for subprocess.Popen: running until `exited`, with a name for the record."""

    def __init__(self, name: str, exited: bool = False) -> None:
        self.name = name
        self.exited = exited

    def poll(self) -> int | None:
        return 0 if self.exited else None


def _recording() -> tuple[ChildRegistry, list[str]]:
    killed: list[str] = []
    return ChildRegistry(kill=lambda proc: killed.append(proc.name)), killed


def test_register_and_unregister_track_the_live_processes() -> None:
    registry, killed = _recording()
    first, second = FakeProc("first"), FakeProc("second")
    assert registry.register(first) is True
    assert registry.register(second) is True
    assert set(registry.live()) == {first, second}
    registry.unregister(first)
    registry.unregister(first)  # a second unregister is harmless
    assert registry.live() == (second,)
    assert killed == []


def test_kill_all_ends_the_running_ones_and_skips_the_exited_ones() -> None:
    """An exited process is not killed again: its pid could already belong to someone else."""
    registry, killed = _recording()
    registry.register(FakeProc("running"))
    registry.register(FakeProc("gone", exited=True))
    assert registry.kill_all() == 1
    assert killed == ["running"]
    assert registry.live() == ()


def test_kill_all_survives_a_kill_that_fails() -> None:
    attempts: list[str] = []

    def kill(proc: FakeProc) -> None:
        attempts.append(proc.name)
        raise OSError("access denied")

    registry = ChildRegistry(kill=kill)
    registry.register(FakeProc("a"))
    registry.register(FakeProc("b"))
    assert registry.kill_all() == 0
    assert sorted(attempts) == ["a", "b"]


def test_kill_all_ends_processes_in_parallel_within_its_wait() -> None:
    """One taskkill takes about 0.4 s; several in a row, or one that hangs, must not push the
    service's shutdown past its eight-second budget."""
    started: list[str] = []
    release = threading.Event()

    def slow_kill(proc: FakeProc) -> None:
        started.append(proc.name)
        release.wait(5)

    registry = ChildRegistry(kill=slow_kill, wait_s=0.3)
    for name in ("a", "b", "c"):
        registry.register(FakeProc(name))
    began = time.monotonic()
    try:
        registry.kill_all()
        assert time.monotonic() - began < 2.0
        assert sorted(started) == ["a", "b", "c"]  # all three were under way at once
    finally:
        release.set()


def test_a_process_registered_after_kill_all_is_ended_at_once() -> None:
    """A collection thread abandoned at shutdown would otherwise start the next item's Claude
    process after the sweep, and the hard exit does not end children on Windows."""
    registry, killed = _recording()
    registry.kill_all()
    late = FakeProc("late")
    assert registry.register(late) is False
    assert killed == ["late"] and registry.live() == ()


def test_reopen_accepts_processes_again() -> None:
    registry, killed = _recording()
    registry.kill_all()
    registry.reopen()
    proc = FakeProc("next")
    assert registry.register(proc) is True
    assert registry.live() == (proc,) and killed == []


def test_registration_from_many_threads_is_safe() -> None:
    registry, _killed = _recording()

    def churn() -> None:
        for i in range(200):
            proc = FakeProc(str(i))
            registry.register(proc)
            registry.unregister(proc)

    threads = [threading.Thread(target=churn) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert registry.live() == ()


def test_the_module_functions_use_the_current_registry(monkeypatch) -> None:
    registry, killed = _recording()
    monkeypatch.setattr(child_processes, "CHILDREN", registry)
    proc = FakeProc("p")
    assert child_processes.register(proc) is True
    assert child_processes.kill_all() == 1
    child_processes.unregister(proc)
    child_processes.reopen()
    assert killed == ["p"] and registry.register(FakeProc("q")) is True


def _python(code: str) -> subprocess.Popen:
    """Start a hidden Python child the way the service starts Claude."""
    kwargs: dict = ({"creationflags": subprocess.CREATE_NO_WINDOW}  # type: ignore[attr-defined]
                    if sys.platform == "win32" else {"start_new_session": True})
    return subprocess.Popen([sys.executable, "-c", code], **kwargs)  # noqa: S603


def test_the_real_kill_ends_a_running_process() -> None:
    registry = ChildRegistry()
    proc = _python("import time; time.sleep(60)")
    try:
        registry.register(proc)
        assert registry.kill_all() == 1
        assert proc.wait(timeout=10) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_an_already_exited_real_process_is_left_alone() -> None:
    registry = ChildRegistry()
    proc = _python("pass")
    proc.wait(timeout=20)
    registry.register(proc)
    assert registry.kill_all() == 0
