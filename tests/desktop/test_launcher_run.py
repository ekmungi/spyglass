"""Tests for the desktop launcher's start and stop path, with a fake server, tray and platform.

Nothing here starts a real service, tray, browser or registry write: the server's run() blocks on
an event, the tray's run() blocks until stop(), and the probe reports what the fakes are doing.
"""

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import spyglass_service.desktop.launcher as launcher_mod
from spyglass_service import __version__
from spyglass_service.desktop.__main__ import main
from spyglass_service.desktop.datadir import DesktopConfig, record_data_version, save_config
from spyglass_service.desktop.launcher import (
    PEER_NOT_ANSWERING_MESSAGE,
    Health,
    Launcher,
    port_busy_message,
    refusal_message,
)
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
        self.born = None  # what process_started_at answers for every pid
        self.asked: list[int] = []
        self.boot = None  # what boot_time answers

    def process_started_at(self, pid: int):
        self.asked.append(pid)
        return self.born

    def boot_time(self):
        return self.boot

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
        monkeypatch.setattr(launcher_mod, "OPEN_WAIT_S", 3.0)
        monkeypatch.setattr(launcher_mod, "POLL_S", 0.01)
        self.behaviour = behaviour
        self.stop_during_build = False
        self.health = health  # a fixed answer for the probe; None means "ask the fakes"
        self.order: list[str] = []
        self.servers: list[FakeServer] = []
        self.trays: list[FakeTray] = []
        self.opened: list[str] = []
        self.open_times: list[float] = []  # self.now() at each opening
        self.now = time.monotonic
        self.exits: list[int] = []
        self.platform = FakePlatform()
        self.launcher = Launcher(
            server_factory=self.make_server, tray_factory=self.make_tray,
            open_browser=self.open_browser, platform=self.platform,
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
        if self.stop_during_build:
            on_stop()  # a stop (the page, the tray) that lands while the server is being built
        return server

    def open_browser(self, url: str) -> None:
        self.opened.append(url)
        self.open_times.append(self.now())

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


class FakeClock:
    """The launcher's clock: it moves only when the launcher sleeps, so minutes pass at once.

    With `pause_at`, the sleep that reaches that time blocks until `resume` is set, so a test
    can act (press Quit) at a known moment of the wait.
    """

    def __init__(self, pause_at: float | None = None) -> None:
        self.now = 0.0
        self.pause_at = pause_at
        self.paused = threading.Event()
        self.resume = threading.Event()

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.pause_at is not None and self.now >= self.pause_at and not self.resume.is_set():
            self.paused.set()
            self.resume.wait(WAIT)


def _slow_service(rig: Rig, monkeypatch, answer_at: float | None,
                  pause_at: float | None = None) -> FakeClock:
    """Real waits (30 s before the tray, 120 s in all) on a fake clock; the service first answers
    its health probe at `answer_at` seconds, or never when None."""
    clock = FakeClock(pause_at)
    monkeypatch.setattr(launcher_mod, "time", SimpleNamespace(monotonic=clock.monotonic,
                                                              sleep=clock.sleep))
    monkeypatch.setattr(launcher_mod, "HEALTH_WAIT_S", 30.0)
    monkeypatch.setattr(launcher_mod, "OPEN_WAIT_S", 120.0)
    monkeypatch.setattr(launcher_mod, "POLL_S", 0.25)
    monkeypatch.setattr(
        launcher_mod, "probe_health",
        lambda port, timeout=1.0: (Health(__version__, "desktop")
                                   if answer_at is not None and clock.now >= answer_at else None))
    rig.now = clock.monotonic
    return clock


def _wait_until(condition) -> None:
    deadline = time.monotonic() + WAIT
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def test_a_slow_first_start_opens_the_page_on_the_first_answer(make_rig, monkeypatch) -> None:
    """A first start after an install can take longer than the 30 s before the tray shows. The
    page then opens when the service first answers, not on a port that is not listening yet."""
    rig = make_rig()
    _slow_service(rig, monkeypatch, answer_at=45.0)
    rig.start()
    tray = rig.wait_for_tray()
    _wait_until(lambda: rig.opened)
    assert rig.opened == [URL]
    assert rig.open_times == [pytest.approx(45.0, abs=0.5)]
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_a_service_that_never_answers_gets_its_page_opened_at_120_seconds(
        make_rig, monkeypatch) -> None:
    rig = make_rig()
    _slow_service(rig, monkeypatch, answer_at=None)
    rig.start()
    tray = rig.wait_for_tray()
    _wait_until(lambda: rig.opened)
    assert rig.opened == [URL]
    assert rig.open_times == [pytest.approx(120.0, abs=0.5)]
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_quit_while_waiting_for_the_first_answer_opens_nothing(make_rig, monkeypatch) -> None:
    """The tray is up while the page waits, and Quit from it ends the wait and the app."""
    rig = make_rig()
    clock = _slow_service(rig, monkeypatch, answer_at=None, pause_at=60.0)
    rig.start()
    tray = rig.wait_for_tray()
    assert clock.paused.wait(WAIT), "the page never waited past the tray"
    tray.kwargs["on_quit"]()
    clock.resume.set()
    assert rig.finish() == 0
    time.sleep(0.1)  # a waiter that ignored the stop would open the page now
    assert rig.opened == []


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


PEER_LOCKED_AT = datetime(2026, 11, 14, 8, 0, 0, tzinfo=UTC)
GENUINE = PEER_LOCKED_AT - timedelta(seconds=10)  # the holder's process predates its lock
REUSED = PEER_LOCKED_AT + timedelta(hours=1)  # a process created after the lock: a reused pid


def _peer_lock(rig: Rig, monkeypatch, born) -> str:
    """Leave a lock as a launcher would; every holder pid looks alive, and the platform reports
    `born` as the holder process's start."""
    text = json.dumps({"pid": 4242, "started_at": PEER_LOCKED_AT.isoformat()})
    (rig.data / "desktop.lock").write_text(text, encoding="utf-8")
    rig.platform.born = born
    monkeypatch.setattr(
        launcher_mod, "single_instance_lock",
        lambda data_dir, **checks: CycleFileLock(
            data_dir / "desktop.lock", max_age=None, pid_alive=lambda pid: True, **checks))
    return text


def test_a_running_peer_gets_its_dashboard_opened(make_rig, monkeypatch) -> None:
    """A second start on the same folder opens the first one's interface and exits."""
    rig = make_rig(health=Health(__version__, "desktop"))
    text = _peer_lock(rig, monkeypatch, GENUINE)
    assert rig.launcher.run(background=False) == 0
    assert rig.opened == [URL] and rig.order == [] and rig.trays == []
    assert (rig.data / "desktop.lock").read_text(encoding="utf-8") == text


def test_a_running_peer_with_background_opens_nothing(make_rig, monkeypatch) -> None:
    rig = make_rig(health=Health(__version__, "desktop"))
    _peer_lock(rig, monkeypatch, GENUINE)
    assert rig.launcher.run(background=True) == 0
    assert rig.opened == [] and rig.order == []


def test_a_lock_holding_a_reused_pid_is_taken_at_once(make_rig, monkeypatch) -> None:
    """Windows reuses pids, so a crash-left lock can name a live, unrelated process. Its process
    started after the lock was written, so the lock is stale: taken without any wait."""
    rig = make_rig()
    monkeypatch.setattr(launcher_mod, "PEER_WAIT_S", 30.0)  # would show if it waited
    old = _peer_lock(rig, monkeypatch, REUSED)
    began = time.monotonic()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    assert time.monotonic() - began < 3.0
    assert 4242 in rig.platform.asked
    lock_text = (rig.data / "desktop.lock").read_text(encoding="utf-8")
    assert lock_text != old and json.loads(lock_text)["pid"] == os.getpid()
    assert rig.order == ["redirect", "server"]
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


def test_a_genuine_holder_is_never_taken_over(make_rig, monkeypatch) -> None:
    """A live launcher that is slow to start (or shows a message box) keeps its lock. After the
    wait the second start says so and exits; it neither starts nor deletes anything."""
    rig = make_rig()
    old = _peer_lock(rig, monkeypatch, GENUINE)
    assert rig.launcher.run(background=False) == 0
    assert rig.platform.messages == [("Spyglass", PEER_NOT_ANSWERING_MESSAGE)]
    assert PEER_NOT_ANSWERING_MESSAGE == (
        "Spyglass is still starting or is not responding. Wait a moment, then open it again.")
    assert rig.order == [] and rig.trays == [] and rig.opened == []
    assert (rig.data / "desktop.lock").read_text(encoding="utf-8") == old


def test_a_lock_from_before_the_last_boot_is_taken(make_rig, monkeypatch) -> None:
    """A Windows restart ends the launcher without removing its lock. If the old pid now names a
    process whose start time cannot be read, the boot time still shows the lock is stale, so the
    start goes ahead at once instead of waiting and refusing for the whole session."""
    rig = make_rig()
    monkeypatch.setattr(launcher_mod, "PEER_WAIT_S", 30.0)  # would show if it waited
    old = _peer_lock(rig, monkeypatch, None)
    rig.platform.boot = PEER_LOCKED_AT + timedelta(hours=1)
    began = time.monotonic()
    rig.start(background=True)
    tray = rig.wait_for_tray()
    assert time.monotonic() - began < 3.0
    lock_text = (rig.data / "desktop.lock").read_text(encoding="utf-8")
    assert lock_text != old and json.loads(lock_text)["pid"] == os.getpid()
    assert rig.platform.messages == []
    tray.kwargs["on_quit"]()
    assert rig.finish() == 0


@pytest.mark.parametrize("boot", [None, PEER_LOCKED_AT - timedelta(hours=1)])
def test_a_holder_of_unknown_age_is_treated_as_genuine(make_rig, monkeypatch, boot) -> None:
    """When the platform cannot tell when the holder started, nothing is taken over: neither
    when the boot time is unknown nor when the lock was written since the last boot."""
    rig = make_rig()
    old = _peer_lock(rig, monkeypatch, None)
    rig.platform.boot = boot
    assert rig.launcher.run(background=True) == 0
    assert rig.platform.messages == [("Spyglass", PEER_NOT_ANSWERING_MESSAGE)]
    assert (rig.data / "desktop.lock").read_text(encoding="utf-8") == old


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


def test_stop_returns_at_once_even_when_the_service_is_stuck(make_rig) -> None:
    """stop() runs inside the /api/shutdown request, which must answer 202 without waiting."""
    rig = make_rig(behaviour="stuck", join_timeout=5.0)
    rig.start(background=True)
    rig.wait_for_tray()
    began = time.monotonic()
    rig.launcher.stop()
    assert time.monotonic() - began < 0.5
    rig.servers[0].release.set()  # the service ends within join_timeout: no hard exit
    assert rig.finish() == 0
    assert rig.exits == []


def test_a_stop_while_the_server_is_built_keeps_it_from_starting(make_rig) -> None:
    """A stop that lands before the service thread exists must still win: nothing starts."""
    rig = make_rig()
    rig.stop_during_build = True
    rig.start(background=False)
    assert rig.finish() == 0
    server = rig.servers[0]
    assert server.should_exit is True and not server.started.is_set()
    assert rig.trays == [] and rig.opened == [] and rig.exits == []


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


def test_the_process_ends_hard_after_run_with_its_logs_flushed(monkeypatch) -> None:
    """pystray's setup thread is not a daemon, so after run() the process ends with os._exit;
    the log streams are flushed first so nothing written is lost."""
    from spyglass_service.desktop import __main__ as desktop_main

    events: list = []

    class Stream:
        def __init__(self, name: str) -> None:
            self.name = name

        def flush(self) -> None:
            events.append(("flush", self.name))

    monkeypatch.setattr(desktop_main.sys, "stdout", Stream("out"))
    monkeypatch.setattr(desktop_main.sys, "stderr", Stream("err"))
    desktop_main.end_process(3, exit_now=lambda code: events.append(("exit", code)))
    assert events == [("flush", "out"), ("flush", "err"), ("exit", 3)]


def test_ending_the_process_survives_missing_or_broken_streams(monkeypatch) -> None:
    """Under pythonw the streams may be None, or a log file may be gone; the exit still happens."""
    from spyglass_service.desktop import __main__ as desktop_main

    class Broken:
        def flush(self) -> None:
            raise OSError("the disk went away")

    exits: list[int] = []
    monkeypatch.setattr(desktop_main.sys, "stdout", None)
    monkeypatch.setattr(desktop_main.sys, "stderr", Broken())
    desktop_main.end_process(1, exit_now=exits.append)
    assert exits == [1]
