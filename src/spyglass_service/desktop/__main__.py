"""Entry point of the desktop app: `python -m spyglass_service.desktop`."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spyglass_service import __version__
from spyglass_service.desktop.datadir import check_data_dir, config_path
from spyglass_service.desktop.platform_base import default_platform
from spyglass_service.desktop.platform_calls import PlatformCalls

# Beside desktop.json (%LOCALAPPDATA%\Spyglass), which exists before any data folder does.
CRASH_LOG_NAME = "launcher-crash.log"
# main()'s result after an unexpected error.
EXIT_CRASHED = 1


def _check_data_dir(path: str) -> int:
    """Print why a data folder is unsuitable (if it is) and return the verdict as an exit code.

    must_exist=False because the installer runs this before it creates the folder.
    """
    verdict, message = check_data_dir(Path(path), __version__, must_exist=False)
    if message:
        print(message)
    return int(verdict)


def main(argv: list[str] | None = None) -> int:
    """Run the desktop app, or just check a data folder when --check-data-dir is given."""
    parser = argparse.ArgumentParser(prog="spyglass", description="Spyglass desktop app")
    parser.add_argument("--check-data-dir", metavar="PATH",
                        help="check that PATH suits this version; exit 0, 3 (older data) or 4 (newer)")
    parser.add_argument("--background", action="store_true",
                        help="start without opening the interface in the browser")
    args = parser.parse_args(argv)
    if args.check_data_dir is not None:
        # Not guarded: the installer reads this path's exit code and output, never a message box.
        return _check_data_dir(args.check_data_dir)
    try:
        # Imported here so the folder check stays fast and free of the launcher's heavy imports.
        from spyglass_service.desktop.launcher import Launcher

        return Launcher().run(background=args.background)
    except Exception as exc:
        return _report_crash(exc)


def _write_crash_log(path: Path, details: str) -> bool:
    """Append `details` to the crash log at `path`, creating its folder; False if that failed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as log:
            log.write(f"{datetime.now().isoformat()} Spyglass {__version__}\n{details}\n")
    except OSError:
        return False
    return True


def _crash_message(exc: BaseException, log: Path | None) -> str:
    """What the message box says: where the log is, or the error itself when there is no log."""
    if log is not None:
        return f"Spyglass could not start. Details are in {log}."
    lines = str(exc).splitlines()
    detail = f": {lines[0]}" if lines else ""
    return f"Spyglass could not start: {type(exc).__name__}{detail}"


def _report_crash(exc: BaseException) -> int:
    """Write an unexpected error's traceback to the crash log and tell the user about it.

    Under pythonw an escaped exception is invisible, and it can happen before the service logs
    exist (a settings file that cannot be read, a read-only data folder). Failing to write the
    log must not hide the message, which then names the error instead of a missing file.
    """
    try:
        path = config_path().parent / CRASH_LOG_NAME
    except Exception:
        path = Path(CRASH_LOG_NAME)
    written = _write_crash_log(path, "".join(traceback.format_exception(exc)))
    try:
        platform = default_platform()
    except Exception:
        platform = None
    PlatformCalls(platform).show("Spyglass", _crash_message(exc, path if written else None))
    return EXIT_CRASHED


def end_process(code: int, exit_now: Callable[[int], object] = os._exit) -> None:
    """Flush the log streams, then end the process at once with `code`.

    By the time main() returns, the service has stopped (or never started), but a leftover
    thread could still keep a normal exit waiting: pystray's setup thread is not a daemon. A
    stream that is missing (pythonw) or cannot be flushed must not stop the exit.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass
    exit_now(code)


if __name__ == "__main__":
    end_process(main())
