"""A lock file in the data directory so two service processes never run a cycle at once.

The in-process lock only protects one process. If the service is restarted while the old
process is still finishing a cycle, both would otherwise judge the same items and pay twice.
The lock file is created with an exclusive open and holds the owner's pid and start time. A
lock whose owner is no longer running, or that is far older than any cycle could take, is
stale and taken over. A tiny window remains in which two processes that both found the same
stale lock could race; each re-reads the file just before removing it, which narrows it.
"""

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# A cycle never legitimately runs this long; an older lock is stale even if its pid is in use
# again (process ids are reused).
MAX_LOCK_AGE = timedelta(hours=12)
# An empty or unreadable lock this young is probably being written by its owner right now.
UNREADABLE_GRACE = timedelta(minutes=1)

PidAlive = Callable[[int], bool]


def pid_alive(pid: int) -> bool:
    """True when a process with this id is running.

    On Windows this opens the process for a status query (`os.kill` there would end it); on
    other systems it sends signal 0, which checks without affecting the process.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists but belongs to another user
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    """Windows: open the process with query rights and read its exit code."""
    import ctypes
    from ctypes import wintypes

    query_limited_information, still_active, access_denied = 0x1000, 259, 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # cannot tell; assume it is alive rather than steal its lock
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


class CycleFileLock:
    """An exclusive lock file holding {"pid", "started_at"}.

    Args:
        path: Where the lock file lives (normally in the data directory).
        pid_alive: Liveness check for the holder's pid (replaced in tests).
        pid: This process's id (replaced in tests to act as another process).
    """

    def __init__(self, path: Path, *, pid_alive: PidAlive = pid_alive,
                 pid: int | None = None) -> None:
        self.path = Path(path)
        self._alive = pid_alive
        self._pid = pid if pid is not None else os.getpid()
        self._mine: str | None = None

    def acquire(self) -> bool:
        """Take the lock; False when another live process holds it."""
        for _ in range(2):  # a second try after removing a stale lock
            if self._create():
                return True
            seen = self._read_text()
            if not self._is_stale(seen):
                return False
            if self._read_text() == seen:  # still the same stale holder: remove it
                logger.warning("taking over a stale radar cycle lock: %s", (seen or "").strip())
                self._remove()
        return False

    def release(self) -> None:
        """Remove the lock if it is still ours (never another process's lock)."""
        if self._mine is not None and self._read_text() == self._mine:
            self._remove()
        self._mine = None

    def _create(self) -> bool:
        """Create the file exclusively and write our holder record; False if it exists."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        text = json.dumps({"pid": self._pid, "started_at": datetime.now(UTC).isoformat()})
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        self._mine = text
        return True

    def _read_text(self) -> str | None:
        """The lock file's text, or None when it does not exist or cannot be read."""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _is_stale(self, text: str | None) -> bool:
        """True when the holder is gone, or the lock is too old to belong to a real cycle."""
        if text is None:
            return not self.path.exists()
        try:
            holder = json.loads(text)
            pid = int(holder["pid"])
            started = datetime.fromisoformat(holder["started_at"])
        except (ValueError, KeyError, TypeError):
            return self._age_of_file() > UNREADABLE_GRACE
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if pid == os.getpid() and self._pid == os.getpid():
            return True  # left by this very process; the in-process lock guards it now
        if datetime.now(UTC) - started > MAX_LOCK_AGE:
            return True
        return not self._alive(pid)

    def _age_of_file(self) -> timedelta:
        """How long ago the lock file was last written."""
        try:
            modified = datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
        except OSError:
            return timedelta(0)
        return datetime.now(UTC) - modified

    def _remove(self) -> None:
        """Delete the lock file; a file already gone is fine."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("could not remove the radar cycle lock %s", self.path)
