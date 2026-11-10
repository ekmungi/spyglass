"""Tests for the background fetch queue.

The queue turns on-demand full-text fetch into a job whose state lives in the DB, so
progress survives the reader pane being destroyed on navigation.
"""

from sqlmodel import Session, select

from spyglass_service.fetch_queue import active_card_ids, enqueue, job_for_card
from spyglass_service.models import FetchJob


def test_enqueue_creates_a_queued_job(engine_with_card):
    """A fresh enqueue records a job in 'queued' for that card."""
    job = enqueue(engine_with_card, card_id=1)

    assert job.card_id == 1
    assert job.status == "queued"
    assert job.started_at is None
    assert job.finished_at is None


def test_enqueue_twice_returns_the_existing_job(engine_with_card):
    """Double-clicking the button must not queue the same card twice."""
    first = enqueue(engine_with_card, card_id=1)
    second = enqueue(engine_with_card, card_id=1)

    assert second.id == first.id
    with Session(engine_with_card) as session:
        rows = session.exec(select(FetchJob)).all()
    assert len(rows) == 1


def test_job_for_card_returns_none_when_never_enqueued(engine_with_card):
    """A card nobody has fetched has no job to report."""
    assert job_for_card(engine_with_card, card_id=1) is None


def test_active_card_ids_lists_only_non_terminal_jobs(engine_with_two_cards):
    """The list-row indicator reads this; a finished job must not keep a row spinning."""
    enqueue(engine_with_two_cards, card_id=1)
    done = enqueue(engine_with_two_cards, card_id=2)
    with Session(engine_with_two_cards) as session:
        row = session.get(FetchJob, done.id)
        row.status = "done"
        session.add(row)
        session.commit()

    assert active_card_ids(engine_with_two_cards) == [1]
