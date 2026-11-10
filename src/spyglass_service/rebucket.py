# src/spyglass_service/rebucket.py
"""One-time re-bucket migration: go-forward + re-bucket recent.

compose_due_briefs composes one brief per un-briefed local publish-day. Briefs
composed BEFORE that swap still carry the OLD fetch-windowed shape: a single brief can
span several distinct local days, which is exactly what publish-day windowing exists to
prevent. Rather than rewrite old history (older briefs are left as-is, preserved), this
migration resets only the RECENT ones -- un-stamping their cards' brief_id and deleting
the Brief rows -- so the very next compose_due_briefs pass rebuilds those days into
proper per-day briefs (one per publish-day). It is a one-shot: guarded by a RunLog marker (the same
one-time-migration pattern categories.migrate_categories_once already uses) so it never
re-runs and re-resets a brief the user has since reviewed.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Brief, Card, RunLog

logger = logging.getLogger(__name__)

# RunLog.source sentinel marking that the one-time reset has already run. Mirrors
# categories._CATEGORY_MIGRATE_MARKER's pattern: presence of a RunLog row with this
# source is the durable, atomic "done" flag -- no new table needed.
_REBUCKET_MARKER = "publish_day_rebucket_done"

# How many days back from "today" count as "recent" (and therefore get reset). Bounds
# the reset to the fetch-windowed briefs the new publish-day windowing would re-partition
# into per-day briefs; older briefs are preserved as history.
_DEFAULT_CUTOFF_DAYS = 5


def rebucket_recent_briefs(
    engine: Engine, *, today: date | None = None, cutoff_days: int = _DEFAULT_CUTOFF_DAYS
) -> list[int]:
    """Reset every RECENT brief so the next compose pass rebuilds it into per-day briefs.

    "Recent" means covers_until >= local midnight of (today - cutoff_days), inclusive --
    the same window compose_due_briefs' newest days would occupy. For each such brief,
    in ONE transaction: every Card.brief_id pointing at it is reset to NULL (so those
    cards become eligible again), then the Brief row itself is deleted. Briefs older
    than the cutoff are left completely untouched -- they stay as historical record.

    This function does no composing itself; it only clears the way. The startup site
    is expected to call compose_due_briefs immediately after, which re-partitions the
    now-unstamped cards into proper publish-day buckets.

    Args:
        engine: SQLAlchemy engine.
        today: The "today" cap used to compute the cutoff; None means the real
            current UTC date (production default; tests pass an explicit date).
        cutoff_days: How many days back from today counts as "recent" (inclusive
            boundary). Defaults to 5, matching compose_due_briefs' bucket cap.

    Returns:
        The ids of the Brief rows that were deleted (empty when nothing was recent).
    """
    cap = today if today is not None else datetime.now(UTC).date()
    # Naive-UTC midnight of the cutoff day, comparable directly to Brief.covers_until
    # (also naive UTC, per the schema's storage convention -- see models.py).
    cutoff = datetime.combine(cap - timedelta(days=cutoff_days), datetime.min.time())

    deleted_ids: list[int] = []
    with Session(engine) as session:
        recent = list(
            session.exec(select(Brief).where(Brief.covers_until >= cutoff)).all()
        )
        for brief in recent:
            # Un-stamp every card this brief claimed -- they must become eligible again
            # before the brief row disappears, or a crash mid-migration could leave a
            # card permanently orphaned (brief_id pointing at a row that no longer exists).
            cards = list(session.exec(select(Card).where(Card.brief_id == brief.id)).all())
            for card in cards:
                card.brief_id = None
                session.add(card)
            session.delete(brief)
            deleted_ids.append(brief.id)
        session.commit()  # one transaction: every un-stamp + every delete lands together

    if deleted_ids:
        logger.info(
            "rebucket_recent_briefs: reset %d recent brief(s) for publish-day re-partitioning: %s",
            len(deleted_ids), deleted_ids,
        )
    return deleted_ids


def _rebucket_marker_done(engine: Engine) -> bool:
    """True once the one-time re-bucket reset has already run (RunLog marker present)."""
    with Session(engine) as session:
        row = session.exec(select(RunLog).where(RunLog.source == _REBUCKET_MARKER)).first()
    return row is not None


def _set_rebucket_marker(engine: Engine) -> None:
    """Record that the one-time re-bucket reset has run, so it never runs again."""
    with Session(engine) as session:
        session.add(RunLog(source=_REBUCKET_MARKER, status="ok"))
        session.commit()
