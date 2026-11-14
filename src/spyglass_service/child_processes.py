"""The child processes the service starts on its own, so that a stop can end them all at once.

The Claude job worker ends its own runs. Two other paths start Claude (or another engine's
program) and are only abandoned at a stop: a judging call (`claude -p` once per item, inside a
collection's daemon thread) and a streaming assistant reply. The desktop app then ends with a
hard exit, which on Windows does not end child processes, so each of those paths registers its
process here for as long as it runs, and the service's shutdown calls `kill_all()` first.

After `kill_all()` the registry stays closed until `reopen()`: a process registered then is
ended at once, because an abandoned collection thread would otherwise start the next item's
process after the sweep. A process started for the user, such as the browser opened on its
extensions page, is never registered: a stop must not close it.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from spyglass_service.claude_jobs import _kill_tree

logger = logging.getLogger(__name__)

# A started process: subprocess.Popen, or a stand-in with poll() in tests.
Proc = Any
# The longest a stop waits for its kills. They run in parallel and one Windows taskkill takes
# about 0.4 s, so this keeps the service's shutdown inside its eight-second budget.
KILL_WAIT_S = 1.0


class ChildRegistry:
    """A thread-safe set of live child processes that a stop ends together.

    Args:
        kill: Ends a process and what it started (replaced in tests).
        wait_s: The longest kill_all() waits for its kills.
    """

    def __init__(self, kill: Callable[[subprocess.Popen], None] = _kill_tree,
                 wait_s: float = KILL_WAIT_S) -> None:
        self._kill = kill
        self._wait_s = wait_s
        self._lock = threading.Lock()
        self._live: set[Proc] = set()
        self._closed = False

    def register(self, proc: Proc) -> bool:
        """Track `proc` until it is unregistered; False (and `proc` ended) after kill_all()."""
        with self._lock:
            if not self._closed:
                self._live.add(proc)
                return True
        logger.warning("Ending a child process started while Spyglass is stopping")
        self._end(proc)
        return False

    def unregister(self, proc: Proc) -> None:
        """Stop tracking `proc` (it ended, or its owner closed it); unknown ones are ignored."""
        with self._lock:
            self._live.discard(proc)

    def live(self) -> tuple[Proc, ...]:
        """The processes tracked right now."""
        with self._lock:
            return tuple(self._live)

    def start_kill_all(self) -> KillRun:
        """Close the registry and start ending every tracked process that still runs; returns
        at once, so the caller can stop other things while the kills run.

        The kills run in parallel (one taskkill takes about 0.4 s). A process that already
        exited is left alone (its pid may be reused) and a kill that fails is logged; neither
        stops the others from being ended. `KillRun.join` waits for them, up to `wait_s` counted
        from this call.
        """
        with self._lock:
            self._closed = True
            procs = list(self._live)
            self._live.clear()
        ended: list[bool] = []  # list.append is atomic, so the kill threads can share it
        threads = [threading.Thread(target=lambda p=proc: ended.append(self._end(p)),
                                    name="spyglass-kill-child", daemon=True) for proc in procs]
        for thread in threads:
            thread.start()
        return KillRun(threads, ended, time.monotonic() + self._wait_s)

    def kill_all(self) -> int:
        """End every tracked process, close the registry, and return how many kills were sent
        within the wait; `start_kill_all` followed at once by its join."""
        return self.start_kill_all().join()

    def reopen(self) -> None:
        """Accept processes again (a service starting in this process)."""
        with self._lock:
            self._closed = False

    def _end(self, proc: Proc) -> bool:
        """Kill `proc` if it still runs; True when a kill was sent without error."""
        try:
            if proc.poll() is not None:
                return False
            self._kill(proc)
            return True
        except Exception:
            logger.exception("Could not end a child process")
            return False


class KillRun:
    """Kills under way. join() waits for them until the deadline set when they started."""

    def __init__(self, threads: list[threading.Thread], ended: list[bool], deadline: float) -> None:
        """`ended` collects one result per finished kill; `deadline` is a monotonic time."""
        self._threads = threads
        self._ended = ended
        self._deadline = deadline

    def join(self) -> int:
        """Wait for the kills, at most until the deadline; how many were sent without error."""
        for thread in self._threads:
            thread.join(max(0.0, self._deadline - time.monotonic()))
        return sum(self._ended)


# The service's registry. The functions below look it up on every call, so tests can replace it.
CHILDREN = ChildRegistry()


def register(proc: Proc) -> bool:
    """Track `proc` in the service's registry; see `ChildRegistry.register`."""
    return CHILDREN.register(proc)


def unregister(proc: Proc) -> None:
    """Stop tracking `proc` in the service's registry."""
    CHILDREN.unregister(proc)


def kill_all() -> int:
    """End every tracked process and close the service's registry; see `ChildRegistry.kill_all`."""
    return CHILDREN.kill_all()


def start_kill_all() -> KillRun:
    """Start ending every tracked process and close the service's registry; join the result."""
    return CHILDREN.start_kill_all()


def reopen() -> None:
    """Let the service's registry accept processes again."""
    CHILDREN.reopen()
