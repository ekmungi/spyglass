# Tests for enrich_is_stale helper and the daily-guarded enrich wiring in startup.
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from spyglass_service.refresh import enrich_is_stale
from spyglass_service.models import RunLog


def test_enrich_is_stale_true_when_never_run(engine):
    """When no enrich RunLog row exists the pipeline is considered stale (first run)."""
    assert enrich_is_stale(engine, timedelta(hours=24)) is True


def test_enrich_is_stale_false_when_recent(engine):
    """A successful enrich run within max_age makes the pipeline fresh (skip duplicate run)."""
    with Session(engine) as s:
        s.add(RunLog(source="enrich", status="ok",
                     started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
        s.commit()
    assert enrich_is_stale(engine, timedelta(hours=24)) is False
