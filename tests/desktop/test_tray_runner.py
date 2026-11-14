"""Tests for TrayRunner: a close is never lost, whenever it comes relative to the tray loop."""

import threading

from spyglass_service.desktop.tray_runner import TrayRunner

WAIT = 5.0


class FakeTray:
    """Like pystray.Icon: stop() does nothing until the loop is live; then run() returns."""

    def __init__(self, before_setup=None) -> None:
        self.visible = False
        self.live = False
        self.ran = False
        self.stopped = threading.Event()
        self.before_setup = before_setup

    def run(self, setup=None) -> None:
        self.ran = True
        if self.before_setup is not None:
            self.before_setup()
        self.live = True
        if setup is not None:
            setup(self)
        self.stopped.wait(WAIT)

    def stop(self) -> None:
        if self.live:
            self.stopped.set()


def test_close_while_live_ends_the_loop() -> None:
    runner, tray = TrayRunner(), FakeTray()
    thread = threading.Thread(target=runner.run, args=(tray,))
    thread.start()
    while not tray.visible:
        threading.Event().wait(0.01)
    runner.close()
    thread.join(WAIT)
    assert not thread.is_alive() and runner.wait_closed(0)


def test_close_before_run_keeps_the_icon_from_appearing() -> None:
    runner, tray = TrayRunner(), FakeTray()
    runner.close()
    runner.run(tray)
    assert tray.ran is False and tray.visible is False
    assert runner.wait_closed(0)


def test_close_between_run_and_live_is_applied_once_live() -> None:
    """pystray would drop this stop; the runner applies it from the setup callback."""
    runner = TrayRunner()
    tray = FakeTray(before_setup=runner.close)
    done = threading.Thread(target=runner.run, args=(tray,))
    done.start()
    done.join(WAIT)
    assert not done.is_alive()
    assert tray.stopped.is_set()


def test_a_failing_stop_is_logged_not_raised(caplog) -> None:
    class BrokenTray(FakeTray):
        def stop(self) -> None:
            raise RuntimeError("icon already gone")

    runner, tray = TrayRunner(), BrokenTray()
    thread = threading.Thread(target=runner.run, args=(tray,), daemon=True)
    thread.start()
    while not tray.visible:
        threading.Event().wait(0.01)
    runner.close()
    assert "could not be closed" in caplog.text
    tray.stopped.set()
    thread.join(WAIT)
