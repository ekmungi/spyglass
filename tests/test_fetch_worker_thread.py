"""Tests for the FetchWorker background thread.

Kept apart from the drain-logic tests: everything interesting about ordering and failure
isolation is covered synchronously in test_fetch_worker.py. These cover only that the
thread starts, picks work up, and stops cleanly. Synchronisation is via Events with
timeouts -- never sleeps.
"""

import threading

import pytest

from spyglass_service.fetch_queue import enqueue, job_for_card
from spyglass_service.fetch_worker import FetchWorker

# This module is the one place that tests the thread itself, so it opts out of the
# conftest guard that keeps FetchWorker.start() inert everywhere else.
pytestmark = pytest.mark.live_fetch_worker


def test_worker_picks_up_a_queued_job_in_the_background(engine_with_card):
    """A job queued before start is drained without anyone calling drain() directly."""
    seen: list[int] = []
    fired = threading.Event()

    def runner(card_id: int) -> None:
        seen.append(card_id)
        fired.set()

    enqueue(engine_with_card, card_id=1)
    worker = FetchWorker(engine_with_card, runner)
    worker.start()
    try:
        assert fired.wait(timeout=5), "worker never picked up the queued job"
    finally:
        worker.stop(timeout=5)

    assert seen == [1]
    # stop() joins, so the terminal write has landed by now.
    assert job_for_card(engine_with_card, card_id=1).status == "done"


def test_wake_processes_a_job_queued_after_start(engine_with_card):
    """Enqueue-then-wake is the production path: the API nudges the worker."""
    fired = threading.Event()
    worker = FetchWorker(engine_with_card, lambda _card_id: fired.set())
    worker.start()
    try:
        enqueue(engine_with_card, card_id=1)
        worker.wake()
        assert fired.wait(timeout=5), "wake() did not cause the job to run"
    finally:
        worker.stop(timeout=5)


def test_stop_returns_promptly_when_the_worker_is_idle(engine_with_card):
    """Shutdown must not hang on an idle worker waiting for its next poll."""
    worker = FetchWorker(engine_with_card, lambda _card_id: None)
    worker.start()

    worker.stop(timeout=5)

    assert not worker.is_alive()


def test_stop_is_safe_when_never_started(engine_with_card):
    """Lifespan teardown may run against a worker that never started (degraded DB)."""
    worker = FetchWorker(engine_with_card, lambda _card_id: None)

    worker.stop(timeout=1)

    assert not worker.is_alive()
