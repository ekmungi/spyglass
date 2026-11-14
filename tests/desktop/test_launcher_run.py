"""Tests for the desktop launcher's start and stop path, with a fake server, tray and platform.

Nothing here starts a real service, tray, browser or registry write: the server's run() blocks on
an event, the tray's run() blocks until stop(), and the probe reports what the fakes are doing.
"""

import json
import os
import threading
import time
from pathlib import Path

import pytest

import spyglass_service.desktop.launcher as launcher_mod
from spyglass_service import __version__
from spyglass_service.desktop.__main__ import main
from spyglass_service.desktop.datadir import DesktopConfig, record_data_version, save_config
from spyglass_service.desktop.launcher import Health, Launcher, port_busy_message, refusal_message
from spyglass_service.radar.cycle_lock import CycleFileLock

PORT = 7790
URL = f"http://127.0.0.1:{PORT}/"
WAIT = 5.0  # generous upper bound for any one step in these tests


class FakeServer:
    """Stands in for uvicorn.Server: run() blocks until should_exit, like the real one.

    behaviour: "normal"; "stuck" (ignores should_exit); "bind_fail" (raises SystemExit(1), as
    uvicorn does when the port cannot be bound); "early" (returns at once, as uvicorn does when
    the app's start-up fails); "raise_on_exit" (setting should_exit raises).
    """

    def __init__(self, behaviour: str = "normal") -> None:
        self.behaviour = behaviour
        self.started = threading.Event()
        self.crash = threading.Event()
        self.release = threading.Event()
        self._exit = threading.Event()
        self.exit_sets = 0

    @property
    def should_exit(self) -> bool:
        return self._exit.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        self.exit_sets += 1
        if self.behaviour == "raise_on_exit":
            raise RuntimeError("the server object is broken")
        if value:
            self._exit.set()

    def run(self) -> None:
        if self.behaviour == "bind_fail":
            raise SystemExit(1)
        if self.behaviour == "early":
            return
        self.started.set()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.crash.is_set() or self.release.is_set():
                return
            if self._exit.is_set() and self.behaviour == "normal":
                return
            time.sleep(0.01)


class FakeTray:
    """Stands in for pystray.Icon. Like the real one, stop() does nothing until the loop runs."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.visible = False
        self.ready = threading.Event()
        self.shown = threading.Event()
        self.stopped = threading.Event()
        self.stop_calls = 0

    def run(self, setup=None) -> None:
        self.ready.set()  # pystray marks itself running before it calls setup
        if setup is not None:
            setup(self)
        self.shown.set()
        self.stopped.wait(30)

    def stop(self) -> None:
        self.stop_calls += 1
        if self.ready.is_set():
            self.stopped.set()


class FakePlatform:
    """Records message boxes and keeps the start-with-Windows switch in memory."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.autostart = False

    def autostart_enabled(self) -> bool:
        return self.autostart

    def set_autostart(self, enabled: bool) -> None:
        self.autostart = enabled

    def installed_browsers(self) -> list:
        return []

    def open_extensions_page(self, browser_id: str) -> None:
        raise KeyError(browser_id)

    def show_message(self, title: str, text: str) -> None:
        self.messages.append((title, text))


class Rig:
    """A Launcher wired to fakes, plus what the fakes saw."""

    def __init__(self, monkeypatch, tmp_path: Path, *, behaviour: str = "normal",
                 join_timeout: float = WAIT, health=None) -> None:
        self.data = tmp_path / "data"
        self.data.mkdir(exist_ok=True)
        self.config = tmp_path / "desktop.json"
        save_config(DesktopConfig(data_dir=self.data, port=PORT), self.config)
        monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(self.config))
        monkeypatch.chdir(tmp_path)  # prepare_environment moves into the data folder
        real_prepare = launcher_mod.prepare_environment
        monkeypatch.setattr(launcher_mod, "prepare_environment",
                            lambda config: real_prepare(config, environ={}))
        monkeypatch.setattr(launcher_mod, "redirect_output",
                            lambda data_dir: self.order.append("redirect"))
        monkeypatch.setattr(launcher_mod, "probe_health", self.probe)
        monkeypatch.setattr(launcher_mod, "PEER_WAIT_S", 0.3)
        monkeypatch.setattr(launcher_mod, "HEALTH_WAIT_S", 2.0)
        monkeypatch.setattr(launcher_mod, "POLL_S", 0.01)
        self.behaviour = behaviour
        self.health = health  # a fixed answer for the probe; None means "ask the fakes"
        self.order: list[str] = []
        self.servers: list[FakeServer] = []
        self.trays: list[FakeTray] = []
        self.opened: list[str] = []
        self.exits: list[int] = []
        self.platform = FakePlatform()
        self.launcher = Launcher(
            server_factory=self.make_server, tray_factory=self.make_tray,
            open_browser=self.opened.append, platform=self.platform,
            exit_process=self.exits.append, join_timeout=join_timeout)
        self.result: list[int] = []
        self.thread: threading.Thread | None = None

    def probe(self, port: int, timeout: float = 1.0):
        assert port == PORT
        if self.health is not None:
            return self.health
        if any(s.started.is_set() and not s.should_exit and not s.crash.is_set()
               for s in self.servers):
            return Health(__version__, "desktop")
        return None

    def make_server(self, settings, on_stop):
        self.order.append("server")
        assert settings.port == PORT and settings.data_dir == self.data
        server = FakeServer(self.behaviour)
        server.on_stop = on_stop
        self.servers.append(server)
        return server

    def make_tray(self, **kwargs) -> FakeTray:
        tray = FakeTray(**kwargs)
        self.trays.append(tray)
        return tray

    def start(self, background: bool = False) -> None:
        """Run the launcher in a thread, as the test plays the user and the service."""
        self.thread = threading.Thread(
            target=lambda: self.result.append(self.launcher.run(background=background)),
            daemon=True)
        self.thread.start()

    def wait_for_tray(self) -> FakeTray:
        deadline = time.monotonic() + WAIT
        while not self.trays and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.trays, "the tray never appeared"
        assert self.trays[0].shown.wait(WAIT)
        return self.trays[0]

    def finish(self) -> int:
        assert self.thread is not None
        self.thread.join(WAIT)
        assert not self.thread.is_alive(), "run() did not return"
        return self.result[0]

    def cleanup(self) -> None:
        for server in self.servers:
            server.release.set()
        for tray in self.trays:
            tray.stopped.set()


@pytest.fixture
def make_rig(monkeypatch, tmp_path):
    """Build Rigs and make sure no fake thread outlives the test."""
    rigs: list[Rig] = []

    def factory(**kwargs) -> Rig:
        rig = Rig(monkeypatch, tmp_path, **kwargs)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.cleanup()


def test_run_starts_the_service_opens_the_browser_and_shows_the_tray(make_rig) -> None:
    """The happy path: logs first, then the service, the browser and the tray; Quit ends it."""
    rig = make_rig()
    rig.start()
    tray = rig.wait_for_tray()
    assert rig.order == ["redirect", "server"]  # handlers must bind to the log files
    assert rig.opened == [URL]
    assert tray.visible is True
    assert tray.kwargs["version"] == __version__
    tray.kwargs["on_open"]()
    assert rig.opened == [URL, URL]
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0
    assert rig.servers[0].should_exit is True
    assert tray.stopped.is_set()
    assert rig.exits == []
    assert not (rig.data / "desktop.lock").exists()


def test_background_start_does_not_open_the_browser(make_rig) -> None:
    """--background (the sign-in start) shows only the tray."""
    rig = make_rig()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    assert rig.opened == []
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_tray_switch_reads_and_flips_start_with_windows(make_rig) -> None:
    """The check item reads the entry each time; a click flips what is actually there."""
    rig = make_rig()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    assert tray.kwargs["autostart"]() is False
    tray.kwargs["toggle_autostart"]()
    assert rig.platform.autostart is True and tray.kwargs["autostart"]() is True
    tray.kwargs["toggle_autostart"]()
    assert rig.platform.autostart is False
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_shutdown_from_the_page_stops_the_tray_too(make_rig) -> None:
    """POST /api/shutdown calls the on_stop the launcher gave build_server: the same stop path."""
    rig = make_rig()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    rig.servers[0].on_stop()
    assert rig.finish() == 0
    assert tray.stopped.is_set() and rig.exits == []


def test_refused_folder_shows_a_message_and_starts_nothing(make_rig) -> None:
    """A folder a newer Spyglass used is refused before any log or service touches it."""
    rig = make_rig()
    record_data_version(rig.data, "99.0.0")
    before = sorted(p.name for p in rig.data.iterdir())
    assert rig.launcher.run(background=True) == 4
    assert len(rig.platform.messages) == 1 and "newer" in rig.platform.messages[0][1]
    assert rig.order == [] and rig.trays == [] and rig.opened == []
    assert sorted(p.name for p in rig.data.iterdir()) == before


def test_missing_data_folder_is_refused_and_not_created(make_rig, tmp_path) -> None:
    """A damaged install whose data folder vanished is told so, and nothing is created."""
    rig = make_rig()
    missing = tmp_path / "gone"
    save_config(DesktopConfig(data_dir=missing, port=PORT), rig.config)
    assert rig.launcher.run(background=True) == 5
    assert "missing" in rig.platform.messages[0][1]
    assert not missing.exists() and rig.order == []


def test_missing_settings_file_says_to_run_the_installer(make_rig, tmp_path, monkeypatch) -> None:
    rig = make_rig()
    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(tmp_path / "nowhere.json"))
    assert rig.launcher.run(background=True) == 1
    assert "Run the Spyglass installer" in rig.platform.messages[0][1]
    assert rig.order == []


def test_damaged_settings_file_says_to_run_the_installer_again(make_rig) -> None:
    rig = make_rig()
    rig.config.write_text("{", encoding="utf-8")
    assert rig.launcher.run(background=True) == 1
    assert "installer again" in rig.platform.messages[0][1]
    assert rig.order == []


def test_a_spyglass_started_another_way_is_refused(make_rig) -> None:
    """A developer service on the port is named, and no second service starts."""
    other = Health("0.40.0", None)
    rig = make_rig(health=other)
    assert rig.launcher.run(background=True) == 1
    assert rig.platform.messages == [("Spyglass", refusal_message(other, PORT))]
    assert rig.order == [] and not (rig.data / "desktop.lock").exists()


def test_a_busy_port_is_refused_without_claiming_the_holder_is_not_spyglass(make_rig) -> None:
    rig = make_rig(health="not-spyglass")
    assert rig.launcher.run(background=True) == 1
    assert rig.platform.messages == [("Spyglass", port_busy_message(PORT))]
    assert rig.order == []


def test_port_busy_message_covers_a_hung_spyglass() -> None:
    """A hung Spyglass also answers as "not-spyglass", so the text must not rule it out."""
    assert port_busy_message(7790) == (
        "Port 7790 is in use by another program, or by a Spyglass that is not responding. "
        "Close it, then open Spyglass again.")


def _peer_lock(rig: Rig, monkeypatch) -> str:
    """Leave a lock as a live launcher would, and make every holder pid look alive."""
    text = json.dumps({"pid": 4242, "started_at": "2026-11-14T08:00:00+00:00"})
    (rig.data / "desktop.lock").write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        launcher_mod, "single_instance_lock",
        lambda data_dir: CycleFileLock(data_dir / "desktop.lock", max_age=None,
                                       pid_alive=lambda pid: True))
    return text


def test_a_running_peer_gets_its_dashboard_opened(make_rig, monkeypatch) -> None:
    """A second start on the same folder opens the first one's interface and exits."""
    rig = make_rig(health=Health(__version__, "desktop"))
    text = _peer_lock(rig, monkeypatch)
    assert rig.launcher.run(background=False) == 0
    assert rig.opened == [URL] and rig.order == [] and rig.trays == []
    assert (rig.data / "desktop.lock").read_text(encoding="utf-8") == text


def test_a_running_peer_with_background_opens_nothing(make_rig, monkeypatch) -> None:
    rig = make_rig(health=Health(__version__, "desktop"))
    _peer_lock(rig, monkeypatch)
    assert rig.launcher.run(background=True) == 0
    assert rig.opened == [] and rig.order == []


def test_a_silent_lock_holder_is_treated_as_stale_and_replaced(make_rig, monkeypatch) -> None:
    """Windows reuses pids, so a crash-left lock can name a live, unrelated process. When no
    Spyglass answers within the wait, the lock is taken over and the normal start goes on."""
    rig = make_rig()
    old = _peer_lock(rig, monkeypatch)
    rig.start(background=True)
    tray = rig.wait_for_tray()
    holder = json.loads((rig.data / "desktop.lock").read_text(encoding="utf-8"))
    assert (rig.data / "desktop.lock").read_text(encoding="utf-8") != old
    assert holder["pid"] == os.getpid()
    assert rig.order == ["redirect", "server"]
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_stop_is_idempotent_across_threads(make_rig) -> None:
    """Quit from the tray and from the page at once: one stop, no hard exit."""
    rig = make_rig()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    barrier = threading.Barrier(2)

    def press() -> None:
        barrier.wait()
        rig.launcher.stop()

    pressers = [threading.Thread(target=press) for _ in range(2)]
    for presser in pressers:
        presser.start()
    for presser in pressers:
        presser.join(WAIT)
    assert rig.finish() == 0
    assert rig.servers[0].exit_sets == 1
    assert rig.exits == []
    assert tray.stopped.is_set()


def test_stuck_service_thread_triggers_the_hard_exit(make_rig) -> None:
    """A service thread still alive after join_timeout must never keep the port: exit(0)."""
    rig = make_rig(behaviour="stuck", join_timeout=0.1)
    rig.start(background=True)
    tray = rig.wait_for_tray()
    rig.launcher.stop()
    assert rig.finish() == 0
    assert rig.exits == [0]
    assert tray.stopped.is_set()


def test_stop_never_raises_and_still_finishes(make_rig) -> None:
    """A failure inside stop must not reach /api/shutdown (it would turn 202 into 500)."""
    rig = make_rig(behaviour="raise_on_exit", join_timeout=0.1)
    rig.start(background=True)
    rig.wait_for_tray()
    assert rig.launcher.stop() is None
    assert rig.finish() == 0
    assert rig.exits == [0]  # the server never heard should_exit, so the hard exit ends it


def test_stop_before_anything_started_is_harmless(make_rig) -> None:
    rig = make_rig()
    rig.launcher.stop()
    rig.launcher.stop()
    assert rig.launcher.wait_until_stopped(WAIT) is True
    assert rig.exits == []


def test_service_crash_removes_the_tray(make_rig) -> None:
    """The icon never shows a Spyglass that is not running."""
    rig = make_rig()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    rig.servers[0].crash.set()
    assert rig.finish() == 1
    assert tray.stopped.is_set()
    assert rig.servers[0].exit_sets == 0 and rig.exits == []


def test_a_port_that_cannot_be_bound_shows_the_port_busy_message(make_rig) -> None:
    """uvicorn raises SystemExit(1) when the bind fails (a listener the probe read as free)."""
    rig = make_rig(behaviour="bind_fail")
    rig.start(background=False)
    assert rig.finish() == 1
    assert rig.platform.messages == [("Spyglass", port_busy_message(PORT))]
    assert rig.trays == [] and rig.opened == []


def test_a_service_that_ends_during_start_points_at_the_log(make_rig) -> None:
    """uvicorn returns early when the app's own start-up fails; that is not a busy port."""
    rig = make_rig(behaviour="early")
    rig.start(background=False)
    assert rig.finish() == 1
    assert len(rig.platform.messages) == 1
    assert "service.err.log" in rig.platform.messages[0][1]
    assert rig.trays == [] and rig.opened == []


def test_main_default_path_builds_and_runs_a_launcher(monkeypatch) -> None:
    """`python -m spyglass_service.desktop [--background]` runs the Launcher, nothing else."""
    calls: list = []

    class FakeLauncher:
        def __init__(self, **kwargs) -> None:
            calls.append(("init", kwargs))

        def run(self, background: bool = False) -> int:
            calls.append(("run", background))
            return 7

    monkeypatch.setattr(launcher_mod, "Launcher", FakeLauncher)
    assert main([]) == 7
    assert main(["--background"]) == 7
    assert calls == [("init", {}), ("run", False), ("init", {}), ("run", True)]
