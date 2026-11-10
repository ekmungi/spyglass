"""Queue bookkeeping for on-demand full-text fetches.

Pure DB reads and writes over the FetchJob table: enqueue a card, look up its job, and
list what is still in flight. The worker that drains the queue lives in fetch_worker.py;
keeping the bookkeeping separate means the API layer can enqueue and report without
importing the threading machinery.
"""

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from spyglass_service.models import FetchJob

# A job is "active" while it is still going to do work, "terminal" once it cannot.
# active_card_ids and the enqueue de-dup both key off this split.
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("done", "failed")


def enqueue(engine: Engine, card_id: int) -> FetchJob:
    """Queue a full-text fetch for a card, or return the job already in flight.

    At most one non-terminal job may exist per card, so a second request
    for a card that is already queued or running is a no-op that returns the existing
    job -- double-clicking the reader's button must not fetch the same article twice.

    Args:
        engine: Application DB engine.
        card_id: Primary key of the card to fetch.

    Returns:
        The newly created job, or the non-terminal job that already existed.
    """
    with Session(engine) as session:
        existing = session.exec(
            select(FetchJob)
            .where(FetchJob.card_id == card_id)
            .where(col(FetchJob.status).in_(ACTIVE_STATUSES))
        ).first()
        if existing is not None:
            return existing
        job = FetchJob(card_id=card_id)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def job_for_card(engine: Engine, card_id: int) -> FetchJob | None:
    """Return the most recent fetch job for a card, or None if it has never been fetched.

    The reader reads this on mount to decide whether to render "fetching", which is what
    makes progress survive navigating away and back.
    """
    with Session(engine) as session:
        return session.exec(
            select(FetchJob)
            .where(FetchJob.card_id == card_id)
            .order_by(col(FetchJob.id).desc())
        ).first()


def active_card_ids(engine: Engine) -> list[int]:
    """Return the card ids with a queued or running job, oldest first.

    Drives the list-row pending marker. Deliberately its own lightweight query rather
    than a field on /api/cards, whose payload is kept lean.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(FetchJob.card_id)
            .where(col(FetchJob.status).in_(ACTIVE_STATUSES))
            .order_by(col(FetchJob.id))
        ).all()
    return list(rows)
