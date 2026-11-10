# tests/test_single_writer.py
"""Tests for SingleWriter: a non-blocking single-writer gate.

The gate serializes the Daily Brief compose pass so two overlapping refresh/startup
passes can't both compose the same un-briefed day (double-compose race). A second,
concurrent call must skip immediately (return False without running its callable),
never queue behind the first.
"""

import threading

import pytest

from spyglass_service.single_writer import SingleWriter


def test_run_executes_when_gate_free():
    """A call on a free gate runs the callable and returns True."""
    gate = SingleWriter()
    ran = []
    assert gate.run(lambda: ran.append("x")) is True
    assert ran == ["x"]


def test_gate_frees_after_run_completes():
    """The gate is released once a run finishes, so the next call runs too."""
    gate = SingleWriter()
    calls = []
    assert gate.run(lambda: calls.append(1)) is True
    assert gate.run(lambda: calls.append(2)) is True  # gate free again
    assert calls == [1, 2]


def test_run_skips_without_running_when_gate_already_held():
    """While one call holds the gate, a concurrent call skips: it returns False and
    does NOT run its callable (the in-flight pass already covers the work)."""
    gate = SingleWriter()
    entered = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    def slow():
        entered.set()          # signal we're inside the gate
        release.wait(timeout=2)  # hold it until the test lets go
        ran.append("slow")

    t = threading.Thread(target=lambda: gate.run(slow))
    t.start()
    assert entered.wait(timeout=2)  # first call is now inside the gate

    # Second call while the first still holds the gate: must skip, not queue.
    result = gate.run(lambda: ran.append("second"))
    assert result is False
    assert "second" not in ran

    release.set()
    t.join(timeout=2)
    assert ran == ["slow"]  # only the first call ran its critical section


def test_gate_frees_after_callable_raises():
    """A callable that raises still releases the gate (finally), so the gate does not
    wedge -- a later call runs normally."""
    gate = SingleWriter()

    def boom():
        raise RuntimeError("compose blew up")

    with pytest.raises(RuntimeError):
        gate.run(boom)

    ran = []
    assert gate.run(lambda: ran.append("ok")) is True  # gate was freed despite the raise
    assert ran == ["ok"]


def test_exclusive_blocks_until_gate_free_then_runs():
    """exclusive() is the blocking counterpart of run(): a user-initiated compose that
    MUST run (and needs its result) waits for any in-flight guarded pass, then runs --
    so it can never double-compose alongside a background pass, but is never skipped."""
    gate = SingleWriter()
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def hold():
        def body():
            holding.set()
            release.wait(timeout=2)
            order.append("A")
        gate.run(body)  # non-blocking acquire; holds the gate until `release`

    ta = threading.Thread(target=hold)
    ta.start()
    assert holding.wait(timeout=2)  # A now holds the gate

    ran = threading.Event()

    def b():
        with gate.exclusive():
            order.append("B")
            ran.set()

    tb = threading.Thread(target=b)
    tb.start()
    assert not ran.wait(0.3)  # B must block while A holds the gate

    release.set()
    ta.join(timeout=2)
    tb.join(timeout=2)
    assert ran.is_set()
    assert order == ["A", "B"]  # B ran strictly after A released the gate


def test_exclusive_releases_on_exception():
    """A raising exclusive() body still releases the gate (finally), so it never wedges."""
    gate = SingleWriter()
    with pytest.raises(RuntimeError):
        with gate.exclusive():
            raise RuntimeError("compose blew up")
    ran = []
    assert gate.run(lambda: ran.append("ok")) is True  # gate was freed despite the raise
    assert ran == ["ok"]
