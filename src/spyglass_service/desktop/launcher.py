"""The desktop launcher: it puts the start pieces together, runs the service thread and the tray,
and owns the one stop path.

The pieces themselves (environment, health probe, decision table, messages, logs, lock) live in
`startup.py`; the names the launcher uses are importable from here too. The Launcher's server,
tray, browser, platform and exit are injected, so the whole start and stop path runs in tests
without a tray or a real service.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from spyglass_service import __version__
from spyglass_service.config import Settings
from spyglass_service.desktop.datadir import (
    ConfigError,
    DesktopConfig,
    FolderVerdict,
    check_data_dir,
    load_config,
)
from spyglass_service.desktop.platform_base import DesktopPlatform, default_platform
from spyglass_service.desktop.startup import (
    NO_CONFIG_MESSAGE,
    PEER_NOT_ANSWERING_MESSAGE,
    Health,
    StartAction,
    bad_config_message,
    decide_start,
    port_busy_message,
    prepare_environment,
    probe_health,
    redirect_output,
    refusal_message,
    single_instance_lock,
    start_failed_message,
)
from spyglass_service.desktop.tray_runner import TrayLike, TrayRunner
from spyglass_service.radar.cycle_lock import CycleFileLock

logger = logging.getLogger(__name__)

# How long a second start waits for the running launcher's service to answer. That service does
# its start-up work (backup, migrations, index load) before it opens the port.
PEER_WAIT_S = 30.0
# How long a start waits for its own service to answer before it shows the tray anyway.
HEALTH_WAIT_S = 30.0
# The pause between two health probes while waiting.
POLL_S = 0.25
# Before a hard exit, how long the tray loop gets to remove the icon, so no dead icon lingers.
TRAY_CLOSE_GRACE_S = 0.5
# run()'s result when Spyglass did not start, or stopped on its own.
EXIT_FAILED = 1
MESSAGE_TITLE = "Spyglass"


class ServerLike(Protocol):
    """What the launcher needs from uvicorn.Server."""

    should_exit: bool

    def run(self) -> None:
        """Serve until should_exit is set."""
        ...


def _desktop_server(settings: Settings, on_stop: Callable[[], None]) -> ServerLike:
    """The real service, built as the developer entry builds it and marked as the desktop's."""
    # Imported here: the app is heavy, and it must load only after the logs are redirected.
    from spyglass_service.__main__ import build_server

    return build_server(settings, started_by="desktop", on_stop=on_stop)


def _system_tray(**callbacks: Any) -> TrayLike:
    """The real pystray icon (imported here because pystray is installed on Windows only)."""
    from spyglass_service.desktop.tray import build_tray

    return build_tray(**callbacks)


class Launcher:
    """Starts Spyglass as a tray app and owns its one stop path.

    The tray's Quit, the Settings page's Quit button and POST /api/shutdown all end in stop().
    """

    def __init__(self, *,
                 server_factory: Callable[[Settings, Callable[[], None]], ServerLike] = _desktop_server,
                 tray_factory: Callable[..., TrayLike] = _system_tray,
                 open_browser: Callable[[str], object] = webbrowser.open,
                 platform: DesktopPlatform | None = None,
                 exit_process: Callable[[int], object] = os._exit,
                 join_timeout: float = 10.0) -> None:
        """Each argument defaults to the real thing; platform None means this machine's adapter."""
        self._server_factory = server_factory
        self._tray_factory = tray_factory
        self._open_browser = open_browser
        self._platform = platform if platform is not None else default_platform()
        self._exit_process = exit_process
        self._join_timeout = join_timeout
        self._guard = threading.Lock()
        self._server: ServerLike | None = None
        self._thread: threading.Thread | None = None
        self._tray = TrayRunner()
        self._stopping = False
        self._crashed = False
        self._bind_failed = False
        self._url = ""
        self._stopped = threading.Event()

    def run(self, background: bool = False) -> int:
        """Start Spyglass and block until it stops; return the process exit code.

        Order: settings, environment, lock, start decision, folder check, logs, service thread,
        health wait, the browser unless `background`, then the tray on this (the main) thread.
        0 after a normal stop, or when another live launcher holds this folder; a refused
        folder returns its verdict (3, 4 or 5); every other failure returns 1.
        """
        config = self._read_config()
        if config is None:
            return EXIT_FAILED
        if not config.data_dir.exists():
            # Before the environment (which moves into the folder) and the lock (whose file
            # would create it), so a vanished folder is reported, not silently recreated.
            return self._folder_refusal(config.data_dir) or EXIT_FAILED
        try:
            settings = prepare_environment(config)
        except (OSError, ValueError) as exc:
            self._show(bad_config_message(exc))
            return EXIT_FAILED
        self._url = f"http://127.0.0.1:{settings.port}/"
        lock = single_instance_lock(settings.data_dir, pid_started_at=self._process_started_at)
        try:
            outcome = self._claim(lock, settings.port, background)
            return outcome if outcome is not None else self._start(settings, background)
        finally:
            lock.release()  # deletes the file only if this process wrote it, never a holder's

    def stop(self) -> None:
        """The one stop path. Idempotent, thread-safe, and it never raises.

        It runs inside the request that answers POST /api/shutdown, which must still answer
        202, so it only sets should_exit and hands the rest to a helper thread: joining the
        service thread from one of its own requests would wait for itself. The helper joins
        the service thread for up to join_timeout, closes the tray, and calls exit_process(0)
        only if the thread is still alive, so a stuck thread can never keep the port.
        """
        with self._guard:
            if self._stopping:
                return
            self._stopping = True
            server = self._server
        try:
            if server is not None:
                server.should_exit = True
        except Exception:
            logger.exception("Could not tell the service to stop")
        try:
            threading.Thread(target=self._finish_stop, name="spyglass-stop", daemon=True).start()
        except Exception:
            logger.exception("No thread for the stop; finishing it here")
            self._finish_stop()

    def wait_until_stopped(self, timeout: float | None = None) -> bool:
        """Block until a stop has finished; False if `timeout` passed first."""
        return self._stopped.wait(timeout)

    def _read_config(self) -> DesktopConfig | None:
        """desktop.json, or None after telling the user to run the installer (again)."""
        try:
            config = load_config()
        except ConfigError as exc:
            self._show(bad_config_message(exc))
            return None
        if config is None:
            self._show(NO_CONFIG_MESSAGE)
        return config

    def _claim(self, lock: CycleFileLock, port: int, background: bool) -> int | None:
        """Take the lock and decide whether to start; an exit code means "stop here".

        The lock takes a crash-left lock at once: its holder is gone, or the process now holding
        that pid is newer than the lock (Windows reuses pids). A lock still refused belongs to a
        live launcher, perhaps slow to start or showing a message, and is never taken over:
        wait for its service and open it, or say that it is not answering."""
        if not lock.acquire():
            if self._wait_for_health(port, PEER_WAIT_S, lambda: True):
                if not background:
                    self._open_dashboard()
            else:
                self._show(PEER_NOT_ANSWERING_MESSAGE)
            return 0
        health = probe_health(port)
        action = decide_start(True, health)
        if action is StartAction.REFUSE_OTHER_SPYGLASS and isinstance(health, Health):
            self._show(refusal_message(health, port))
            return EXIT_FAILED
        if action is StartAction.REFUSE_PORT_BUSY:
            self._show(port_busy_message(port))
            return EXIT_FAILED
        return None

    def _folder_refusal(self, data_dir: Path) -> int | None:
        """Show why the data folder is refused and return its verdict; None when it suits."""
        verdict, message = check_data_dir(data_dir, __version__, must_exist=True)
        if verdict is FolderVerdict.OK:
            return None
        self._show(message)
        return int(verdict)

    def _start(self, settings: Settings, background: bool) -> int:
        """Check the folder, redirect the logs, start the service, then run the tray."""
        refused = self._folder_refusal(settings.data_dir)
        if refused is not None:
            return refused
        # Before anything sets up logging (uvicorn does, inside build_server), so every handler
        # binds to the log files and not to the console pythonw does not have.
        redirect_output(settings.data_dir)
        try:
            self._start_service(settings)
        except Exception:
            logger.exception("The service could not be built")
            self._show(start_failed_message(settings.data_dir))
            return EXIT_FAILED
        answered = self._wait_for_health(settings.port, HEALTH_WAIT_S, self._service_running)
        if not self._service_running():
            return self._ended_during_start(settings)
        if not answered:
            logger.warning("The service did not answer within %s s; showing the tray anyway",
                           HEALTH_WAIT_S)
        if not background:
            self._open_dashboard()
        return self._run_tray()

    def _start_service(self, settings: Settings) -> None:
        """Build the server and run it in a non-daemon thread, watched for a crash. A stop that
        came during the build is applied here and nothing starts; starting inside the guard
        means a later stop sees no thread or a running one, never one about to start."""
        server = self._server_factory(settings, self.stop)
        thread = threading.Thread(target=self._serve, args=(server,), name="spyglass-service")
        with self._guard:
            self._server = server
            if self._stopping:
                server.should_exit = True
                return
            self._thread = thread
            thread.start()
        threading.Thread(target=self._watch, args=(thread,), name="spyglass-watch",
                         daemon=True).start()

    def _serve(self, server: ServerLike) -> None:
        """The service thread: run uvicorn and record how it ended."""
        try:
            server.run()
        except SystemExit:
            # uvicorn logs the reason and exits this way when it cannot bind the port, for
            # example to a listener with a full backlog that the probe read as free.
            self._bind_failed = True
        except Exception:
            logger.exception("The service stopped with an error")

    def _watch(self, thread: threading.Thread) -> None:
        """Close the tray when the service ends without a stop: the icon must never show a
        Spyglass that is not running."""
        thread.join()
        with self._guard:
            if self._stopping:
                return
            self._crashed = True
        logger.error("The service stopped on its own; closing the tray")
        self._tray.close()

    def _service_running(self) -> bool:
        """True while the service thread lives and no stop was asked for."""
        with self._guard:
            thread, stopping = self._thread, self._stopping
        return thread is not None and thread.is_alive() and not stopping

    def _wait_for_health(self, port: int, seconds: float, keep_waiting: Callable[[], bool]) -> bool:
        """Probe until a Spyglass answers (True), `seconds` pass, or keep_waiting() turns False."""
        deadline = time.monotonic() + seconds
        while keep_waiting():
            if isinstance(probe_health(port), Health):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_S)
        return False

    def _ended_during_start(self, settings: Settings) -> int:
        """The service ended, or a stop came, before the tray was shown."""
        with self._guard:
            stopping = self._stopping
        if stopping:
            self._stopped.wait()
            return 0
        if self._bind_failed:
            self._show(port_busy_message(settings.port))
        else:
            self._show(start_failed_message(settings.data_dir))
        return EXIT_FAILED

    def _run_tray(self) -> int:
        """Show the tray on this thread until a stop or a crash closes it."""
        try:
            self._tray.run(self._tray_factory(
                on_open=self._open_dashboard, on_quit=self.stop,
                autostart=self._autostart_enabled, toggle_autostart=self._toggle_autostart,
                version=__version__))
        except Exception:
            logger.exception("The tray icon failed")
        with self._guard:
            crashed, stopping = self._crashed, self._stopping
        if crashed:
            return EXIT_FAILED
        if not stopping:
            # The tray ended without a stop, so it failed: never leave a service without an icon.
            self.stop()
            self._stopped.wait()
            return EXIT_FAILED
        self._stopped.wait()
        return 0

    def _finish_stop(self) -> None:
        """Join the service thread, close the tray, and end the process if the thread is stuck."""
        try:
            with self._guard:
                thread = self._thread
            if thread is not None:
                thread.join(self._join_timeout)
            stuck = thread is not None and thread.is_alive()
            self._tray.close()
            if stuck:
                logger.error("The service did not stop within %s s; ending the process",
                             self._join_timeout)
                self._tray.wait_closed(TRAY_CLOSE_GRACE_S)
                self._exit_process(0)
        except Exception:
            logger.exception("Stopping Spyglass failed")
        finally:
            self._stopped.set()

    def _open_dashboard(self) -> None:
        """Open the interface in the default browser."""
        try:
            self._open_browser(self._url)
        except Exception:
            logger.exception("Could not open %s", self._url)

    def _process_started_at(self, pid: int) -> datetime | None:
        """When process `pid` was created, for the lock's reused-pid check; None if unknown."""
        if self._platform is None:
            return None
        try:
            return self._platform.process_started_at(pid)
        except Exception:
            logger.exception("Could not read when process %s started", pid)
            return None

    def _autostart_enabled(self) -> bool:
        """Whether the start-up entry exists; False when it cannot be read."""
        if self._platform is None:
            return False
        try:
            return self._platform.autostart_enabled()
        except Exception:
            logger.exception("Could not read the start-with-Windows entry")
            return False

    def _toggle_autostart(self) -> None:
        """Flip the start-up entry from what is actually there, not from what the menu showed."""
        if self._platform is None:
            return
        try:
            self._platform.set_autostart(not self._platform.autostart_enabled())
        except Exception:
            logger.exception("Could not change the start-with-Windows entry")

    def _show(self, text: str) -> None:
        """Tell the user why Spyglass is not starting: a message box, or stderr without one."""
        if self._platform is not None:
            try:
                self._platform.show_message(MESSAGE_TITLE, text)
                return
            except Exception:
                logger.exception("Could not show a message box")
        print(text, file=sys.stderr)
