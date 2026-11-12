"""Run a command-line engine as a child process and read its output line by line.

The command is started with no console window, the prompt is written to its standard input from
a helper thread (so a large prompt cannot deadlock against a full output pipe), and its output
is read by a second thread into a queue. Reading from the queue with a short wait lets the
caller notice a cancel or a time-out even while the program is silent. `close()` stops the whole
process tree (the program and anything it started) and is safe to call more than once.
"""

import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from spyglass_service.claude_jobs import _kill_tree
from spyglass_service.radar.assist.engines.safe_args import assert_cmd_safe

logger = logging.getLogger(__name__)

_STDERR_KEEP = 4000


class ChildProcess:
    """A started command with its output exposed as an iterator of lines."""

    def __init__(self, command: list[str], *, cwd: Path, env: dict[str, str], stdin_text: str) -> None:
        """Start `command` in `cwd` with `env`; `stdin_text` is sent then the pipe is closed.

        Raises ValueError, before anything starts, when the program is a batch file and an
        argument carries cmd metacharacters.
        """
        assert_cmd_safe(command)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(  # noqa: S603 -- a fixed command; the prompt goes on stdin
            command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kwargs)
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stderr: list[str] = []
        self._threads = [
            threading.Thread(target=self._feed, args=(stdin_text,), daemon=True),
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _feed(self, text: str) -> None:
        """Write the prompt to standard input, then close it so the program starts answering."""
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(text)
            self._proc.stdin.close()
        except (OSError, ValueError):
            pass  # the program exited early; its exit code and stderr say why

    def _read_stdout(self) -> None:
        """Move output lines into the queue; None marks the end of the output."""
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def _read_stderr(self) -> None:
        """Keep the tail of standard error for the failure message."""
        try:
            assert self._proc.stderr is not None
            for line in self._proc.stderr:
                self._stderr.append(line)
                if len(self._stderr) > 80:
                    del self._stderr[:40]
        except (OSError, ValueError):
            pass

    @property
    def stderr_tail(self) -> str:
        """The last part of what the program wrote to standard error."""
        return "".join(self._stderr)[-_STDERR_KEEP:]

    @property
    def returncode(self) -> int | None:
        """The exit code once the program has exited, else None."""
        return self._proc.poll()

    def lines(self, *, timeout_s: float, tick_s: float = 0.25) -> Iterator[str | None]:
        """Yield each output line; yield None whenever `tick_s` passes with nothing new.

        Raises TimeoutError when `timeout_s` has passed since the call started.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                line = self._lines.get(timeout=tick_s)
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise TimeoutError from None
                yield None
                continue
            if line is None:
                return
            yield line

    def close(self) -> None:
        """Stop the process tree if it still runs and release the pipes. Safe to repeat."""
        if self._proc.poll() is None:
            _kill_tree(self._proc)
        for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except (OSError, ValueError):
                pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("An assistant child process did not exit after being killed")
        for thread in self._threads:
            thread.join(timeout=1)
