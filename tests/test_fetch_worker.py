"""Tests for the fetch-queue worker.

The drain logic is pure and synchronous so these tests are deterministic -- no sleeps,
no thread races. The thread wrapper is tested separately for start/stop only.
"""

from sqlmodel import Session, select

from spyglass_service.fetch_queue import enqueue
from spyglass_service.fetch_worker import drain, reset_interrupted, run_next
from spyglass_service.models import FetchJob


def test_run_next_runs_the_job_and_marks_it_done(engine_with_card):
    """The happy path: claim the queued job, run it, record completion."""
    seen: list[int] = []

    processed = run_next(engine_with_card, seen.append)

    assert processed is False  # nothing queued yet
    enqueue(engine_with_card, card_id=1)

    assert run_next(engine_with_card, seen.append) is True
    assert seen == [1]
    with Session(engine_with_card) as session:
        job = session.exec(select(FetchJob)).first()
    assert job.status == "done"
    assert job.started_at is not None
    assert job.finished_at is not None


def test_run_next_records_the_failure_reason_when_the_job_raises(engine_with_card):
    """A failing fetch must be recorded, not swallowed -- the reader shows the reason."""
    enqueue(engine_with_card, card_id=1)

    def boom(_card_id: int) -> None:
        raise RuntimeError("all tiers exhausted")

    assert run_next(engine_with_card, boom) is True

    with Session(engine_with_card) as session:
        job = session.exec(select(FetchJob)).first()
    assert job.status == "failed"
    assert "all tiers exhausted" in job.error
    assert job.finished_at is not None


def test_one_failing_job_does_not_stop_the_queue(engine_with_two_cards):
    """Exception isolation: a poisoned card must not kill the drain."""
    enqueue(engine_with_two_cards, card_id=1)
    enqueue(engine_with_two_cards, card_id=2)
    seen: list[int] = []

    def fail_first(card_id: int) -> None:
        if card_id == 1:
            raise RuntimeError("nope")
        seen.append(card_id)

    processed = drain(engine_with_two_cards, fail_first)

    assert processed == 2
    assert seen == [2]  # the second job still ran
    with Session(engine_with_two_cards) as session:
        statuses = {j.card_id: j.status for j in session.exec(select(FetchJob))}
    assert statuses == {1: "failed", 2: "done"}


def test_drain_processes_jobs_in_fifo_order(engine_with_two_cards):
    """Serial and in order -- queue two, they run oldest first."""
    enqueue(engine_with_two_cards, card_id=2)
    enqueue(engine_with_two_cards, card_id=1)
    seen: list[int] = []

    assert drain(engine_with_two_cards, seen.append) == 2
    assert seen == [2, 1]


def test_reset_interrupted_fails_running_jobs_and_leaves_queued_alone(engine_with_two_cards):
    """Restart semantics: a job cut off mid-run is failed, not lost silently."""
    running = enqueue(engine_with_two_cards, card_id=1)
    enqueue(engine_with_two_cards, card_id=2)
    with Session(engine_with_two_cards) as session:
        row = session.get(FetchJob, running.id)
        row.status = "running"
        session.add(row)
        session.commit()

    reset = reset_interrupted(engine_with_two_cards)

    assert reset == 1
    with Session(engine_with_two_cards) as session:
        statuses = {j.card_id: (j.status, j.error) for j in session.exec(select(FetchJob))}
    assert statuses[1] == ("failed", "interrupted")
    assert statuses[2][0] == "queued"
