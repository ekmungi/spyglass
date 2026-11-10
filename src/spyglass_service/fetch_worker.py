"""Draining the on-demand fetch queue, one job at a time.

The drain logic here is pure and synchronous: `run_next` claims a job, runs an injected
runner, and records the outcome. The background thread that calls it in a loop is a thin
wrapper on top, which keeps the interesting behaviour -- ordering, failure isolation,
restart recovery -- testable without threads or sleeps.

Serial by design: the acquisition ladder's top rung drives a real Chromium
instance, so one job at a time is the intended behaviour, not a limitation.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from spyglass_service.models import FetchJob

logger = logging.getLogger(__name__)

# Given a card id, do the work (in production: fetch + enrich). Injected so the queue
# mechanics can be tested without touching the network or the LLM.
JobRunner = Callable[[int], None]

# Recorded failure text is truncated -- the reader shows a reason, not a stack trace
# (mirrors Feed.last_error).
_MAX_ERROR_CHARS = 500


def run_next(engine: Engine, runner: JobRunner) -> bool:
    """Claim the oldest queued job, run it, and record the outcome.

    The job is marked `running` and committed BEFORE the runner is called, so a crash
    mid-fetch leaves a durable trace that `reset_interrupted` can recover on next start.

    Args:
        engine: Application DB engine.
        runner: Callable invoked with the job's card id.

    Returns:
        True if a job was claimed and run, False if the queue was empty.
    """
    with Session(engine) as session:
        job = session.exec(
            select(FetchJob).where(FetchJob.status == "queued").order_by(col(FetchJob.id))
        ).first()
        if job is None:
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.add(job)
        session.commit()
        job_id, card_id = job.id, job.card_id

    # The runner is user-triggered work over the network; ANY exception must be recorded
    # and contained, never allowed to kill the worker thread.
    error: str | None = None
    try:
        runner(card_id)
    except Exception as exc:  # noqa: BLE001 -- deliberate isolation boundary
        logger.exception("fetch job %s (card %s) failed", job_id, card_id)
        error = (str(exc) or exc.__class__.__name__)[:_MAX_ERROR_CHARS]

    with Session(engine) as session:
        job = session.get(FetchJob, job_id)
        if job is not None:
            job.status = "failed" if error else "done"
            job.error = error
            job.finished_at = datetime.now(UTC)
            session.add(job)
            session.commit()
    return True


def drain(engine: Engine, runner: JobRunner) -> int:
    """Run queued jobs until none remain; return how many were processed.

    A job that fails is still "processed" -- it reaches a terminal state and the next
    job runs, which is the point of the isolation in `run_next`.
    """
    processed = 0
    while run_next(engine, runner):
        processed += 1
    return processed


def reset_interrupted(engine: Engine) -> int:
    """Fail any job left `running` by a previous process; return how many were reset.

    Called at startup. A `running` row means the service died mid-fetch and we cannot
    know how far it got, so it is marked failed with reason `interrupted` rather than
    silently retried -- `enrich_item` is safe to re-run, so the user can simply ask
    again. Jobs left `queued` are untouched and will be picked up normally.
    """
    with Session(engine) as session:
        stuck = session.exec(select(FetchJob).where(FetchJob.status == "running")).all()
        for job in stuck:
            job.status = "failed"
            job.error = "interrupted"
            job.finished_at = datetime.now(UTC)
            session.add(job)
        session.commit()
    if stuck:
        logger.info("reset %d fetch job(s) interrupted by a previous shutdown", len(stuck))
    return len(stuck)


class FetchWorker:
    """The single background thread that drains the fetch queue.

    One thread, one job at a time. `wake()` is how the API nudges it after enqueuing so
    a click is picked up immediately; the poll interval is only a backstop in case a
    wake is ever missed.
    """

    def __init__(self, engine: Engine, runner: JobRunner, poll_interval: float = 2.0) -> None:
        """Args:
        engine: Application DB engine.
        runner: Callable invoked with each job's card id.
        poll_interval: Seconds to wait for a wake before re-checking the queue anyway.
        """
        self._engine = engine
        self._runner = runner
        self._poll_interval = poll_interval
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker thread. A second call while running is a no-op."""
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._loop, name="spyglass-fetch-worker", daemon=True
        )
        self._thread.start()

    def wake(self) -> None:
        """Signal that new work may be queued, so the worker stops waiting and drains."""
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the worker to finish its current job and exit; join up to `timeout`.

        Safe to call when the worker was never started -- lifespan teardown runs even
        when a degraded DB meant the worker never came up.
        """
        self._stopping.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        """Whether the worker thread is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        """Drain, then wait for a wake or the poll interval, until asked to stop.

        `drain` already isolates per-job failures; this extra guard covers a failure in
        the queue bookkeeping itself (e.g. a transient DB error), which must not silently
        kill the only worker the service has.
        """
        while not self._stopping.is_set():
            try:
                drain(self._engine, self._runner)
            except Exception:  # noqa: BLE001 -- the worker thread must outlive any single pass
                logger.exception("fetch worker drain pass failed")
            self._wake.wait(timeout=self._poll_interval)
            self._wake.clear()
