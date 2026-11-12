"""Bounded retries for model replies that were received but could not be used.

A provider outage is not an attempt: those items are simply left for the next run. A reply
that arrived but was malformed is an attempt, and is counted on the item's Assessment, so a
reply the model can never get right stops costing a fetch and a model call every cycle.

- Triage: a failed item is stored with stage "triage_failed" and tier "unjudged" (never
  "out", which would hide it as irrelevant). It is triaged again on later runs until
  MAX_TRIAGE_ATTEMPTS, then left as unjudged.
- Digest: after MAX_DIGEST_ATTEMPTS the item keeps its triage judgement and is not digested
  again.
The error text goes into `Assessment.error`, never into `why`, which the reader sees.
"""

import logging

from sqlalchemy import Engine, update
from sqlmodel import Session, select

from spyglass_service.radar.models import Assessment, utcnow

logger = logging.getLogger(__name__)

# Runs in which an item's triage reply may be unusable before the item is left unjudged.
MAX_TRIAGE_ATTEMPTS = 3
# Runs in which an item's digest reply may be unusable before the triage judgement is kept.
MAX_DIGEST_ATTEMPTS = 2
FAILED_STAGE = "triage_failed"
UNJUDGED_TIER = "unjudged"
# How the earlier code marked a failed triage: score 0 with this text in `why`.
_LEGACY_FAILURE_PREFIX = "triage failed"


def failure_fields(judge_model: str, profile_version: int, error: str) -> dict:
    """Assessment columns for a failed triage (the attempt counter is bumped separately)."""
    return {
        "stage": FAILED_STAGE, "score": 0, "tier": UNJUDGED_TIER, "section": "", "kind": "news",
        "headline": None, "why": None, "key_points": None, "entities": None, "event_key": None,
        "model": judge_model, "profile_version": profile_version, "error": error[:500],
    }


def _bump(engine: Engine, item_id: int, fields: dict, counter: str) -> int:
    """Apply `fields` to the item's Assessment (creating it), add one to `counter`; returns it."""
    with Session(engine) as session:
        row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
        row = row or Assessment(item_id=item_id)
        for name, value in fields.items():
            setattr(row, name, value)
        attempts = int(getattr(row, counter) or 0) + 1
        setattr(row, counter, attempts)
        row.assessed_at = utcnow()
        session.add(row)
        session.commit()
    return attempts


def record_triage_failure(engine: Engine, item_id: int, error: str, *, model: str,
                          profile_version: int) -> int:
    """Store a failed triage for one item and return its failed-attempt count so far."""
    attempts = _bump(engine, item_id, failure_fields(model, profile_version, error),
                     "triage_attempts")
    logger.warning("triage of item %s failed (attempt %d of %d): %s", item_id, attempts,
                   MAX_TRIAGE_ATTEMPTS, error)
    return attempts


def record_digest_failure(engine: Engine, item_id: int, error: str) -> int:
    """Count a failed digest; the triage judgement is kept. Returns the attempt count so far."""
    attempts = _bump(engine, item_id, {"error": error[:500]}, "digest_attempts")
    logger.warning("digest of item %s failed (attempt %d of %d): %s", item_id, attempts,
                   MAX_DIGEST_ATTEMPTS, error)
    return attempts


def convert_legacy_failures(engine: Engine) -> int:
    """Turn failed triages stored by earlier code into retryable failures; returns how many.

    Earlier code stored score 0, tier "out" and the error text in `why`, so the reader saw the
    error as the reason and the item was never judged again. Idempotent.
    """
    stmt = (
        update(Assessment)
        .where(Assessment.stage == "triage", Assessment.score == 0,
               Assessment.why.like(f"{_LEGACY_FAILURE_PREFIX}%"))
        .values(stage=FAILED_STAGE, tier=UNJUDGED_TIER, error=Assessment.why, why=None)
    )
    with Session(engine) as session:
        changed = session.exec(stmt).rowcount  # type: ignore[call-overload]
        session.commit()
    if changed:
        logger.info("converted %d failed triages from the earlier format", changed)
    return int(changed or 0)
