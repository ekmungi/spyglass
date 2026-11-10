"""Refresh orchestration: run every collector, log outcomes, decide staleness."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.cards import materialize_cards
from spyglass_service.collectors.base import Collector
from spyglass_service.collectors.rss import RssCollector, write_feed_health
from spyglass_service.ingest import store_items
from spyglass_service.models import RunLog


def run_refresh(engine: Engine, collectors: list[Collector]) -> int:
    """Run each collector independently and log one RunLog row per source.

    A failing source records an error row and never blocks the others
    (design rule: partial failure must not break the morning briefing).
    After the RSS collector runs, per-feed health is written back onto the
    Feed registry rows so dead/wrong feeds surface as unhealthy.

    Returns the total number of NEW items stored across all sources, so the refresh
    path can force-enrich only when new items actually arrived.
    """
    total_new = 0
    for collector in collectors:
        run = RunLog(source=collector.name, status="running")
        try:
            items = collector.collect()
            new_count = store_items(engine, items)
            total_new += new_count
            run.status = "ok"
            run.detail = f"{new_count} new of {len(items)} fetched"
        except Exception as exc:  # noqa: BLE001 -- each source must stay isolated
            run.status = "error"
            run.detail = str(exc)
        run.finished_at = datetime.now(UTC)
        with Session(engine) as session:
            session.add(run)
            session.commit()
        # Write per-feed health back onto Feed rows immediately after the RSS
        # collector runs so a dead feed no longer fails silently.
        if isinstance(collector, RssCollector):
            write_feed_health(engine, collector._db_path)
    # Every collected item becomes an interactive card immediately; curation
    # enriches these later. Done once after all sources to keep it cheap.
    materialize_cards(engine)
    return total_new


def is_stale(engine: Engine, max_age: timedelta) -> bool:
    """True when the newest successful run is older than max_age (or none exists).

    Failed runs do not reset the clock: only a real success counts as fresh.
    """
    with Session(engine) as session:
        latest = session.exec(
            select(RunLog)
            .where(RunLog.status == "ok")
            .order_by(RunLog.started_at.desc())  # type: ignore[attr-defined]
        ).first()
    if latest is None:
        return True
    started = latest.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) - started > max_age


def enrich_is_stale(engine: Engine, max_age: timedelta) -> bool:
    """True when the newest successful enrich run is older than max_age (or none exists).

    Mirrors is_stale but filters to RunLog rows where source == "enrich", so the
    daily-guard in _schedule_embed only checks the enrichment pipeline's own clock.
    """
    with Session(engine) as session:
        latest = session.exec(
            select(RunLog).where(RunLog.source == "enrich").where(RunLog.status == "ok")
            .order_by(RunLog.started_at.desc())  # type: ignore[attr-defined]
        ).first()
    if latest is None:
        return True
    started = latest.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) - started > max_age
