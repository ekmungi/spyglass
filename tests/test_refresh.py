"""Tests for the refresh orchestrator: per-source runs, partial failure, staleness."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.collectors.rss import RssCollector
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Feed, Item, RunLog
from spyglass_service.refresh import is_stale, run_refresh

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


class FakeCollector:
    """Test double satisfying the Collector protocol."""

    def __init__(self, name: str, items: list[CollectedItem] | None = None, error: bool = False):
        self.name = name
        self._items = items or []
        self._error = error

    def collect(self) -> list[CollectedItem]:
        if self._error:
            raise RuntimeError("source exploded")
        return self._items


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def one_item(name: str) -> CollectedItem:
    return CollectedItem(
        source=name, external_id="1", title="T", url="https://x.test", summary=None,
        published_at=None,
    )


def test_refresh_stores_items_and_logs_one_run_per_source(tmp_path: Path) -> None:
    """Each collector gets its own RunLog row with status ok and a detail count."""
    engine = make_engine(tmp_path)
    collectors = [FakeCollector("rss", [one_item("rss")]), FakeCollector("raindrop", [])]
    run_refresh(engine, collectors)
    with Session(engine) as session:
        runs = session.exec(select(RunLog)).all()
        items = session.exec(select(Item)).all()
    assert {(r.source, r.status) for r in runs} == {("rss", "ok"), ("raindrop", "ok")}
    assert all(r.finished_at is not None for r in runs)
    assert len(items) == 1


def test_run_refresh_returns_total_new_item_count(tmp_path: Path) -> None:
    """run_refresh reports how many NEW items were stored, so the refresh path can
    force-enrich only when new items actually arrived."""
    engine = make_engine(tmp_path)
    collectors = [FakeCollector("rss", [one_item("rss")]), FakeCollector("raindrop", [])]
    assert run_refresh(engine, collectors) == 1


def test_one_failing_source_never_blocks_the_others(tmp_path: Path) -> None:
    """Design rule: partial failure must not block the briefing."""
    engine = make_engine(tmp_path)
    collectors = [FakeCollector("broken", error=True), FakeCollector("rss", [one_item("rss")])]
    run_refresh(engine, collectors)
    with Session(engine) as session:
        runs = {r.source: r for r in session.exec(select(RunLog)).all()}
        items = session.exec(select(Item)).all()
    assert runs["broken"].status == "error"
    assert "source exploded" in (runs["broken"].detail or "")
    assert runs["rss"].status == "ok"
    assert len(items) == 1


def test_fresh_database_is_stale(tmp_path: Path) -> None:
    """No successful run ever -> stale, so the first open triggers a refresh."""
    engine = make_engine(tmp_path)
    assert is_stale(engine, max_age=timedelta(hours=6)) is True


def test_recent_successful_run_is_not_stale(tmp_path: Path) -> None:
    """A successful run inside the window means no refresh needed on open."""
    engine = make_engine(tmp_path)
    run_refresh(engine, [FakeCollector("rss", [])])
    assert is_stale(engine, max_age=timedelta(hours=6)) is False


def test_old_successful_run_is_stale_and_failed_runs_do_not_count(tmp_path: Path) -> None:
    """Staleness keys on the last SUCCESSFUL run; errors do not reset the clock."""
    engine = make_engine(tmp_path)
    old = datetime.now(UTC) - timedelta(days=2)
    with Session(engine) as session:
        session.add(RunLog(source="rss", status="ok", started_at=old, finished_at=old))
        session.add(RunLog(source="rss", status="error", detail="x"))
        session.commit()
    assert is_stale(engine, max_age=timedelta(hours=6)) is True


def test_run_refresh_writes_feed_health_for_rss_collector(tmp_path: Path, fixtures_web_url: str) -> None:
    """run_refresh wires health write-back: Feed row gets last_fetch_status after refresh."""
    engine = make_engine(tmp_path)
    fixture_url = f"{fixtures_web_url}/{FIXTURE.name}"
    with Session(engine) as session:
        session.add(Feed(feed_url=fixture_url, name="Sample", kind="rss", added_via="manual"))
        session.commit()

    collector = RssCollector(
        feed_urls=[fixture_url], reader_db_path=tmp_path / "reader.db"
    )
    run_refresh(engine, [collector])

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == fixture_url)).one()

    assert row.last_fetch_status == "ok"
    assert row.last_fetch_at is not None
    assert row.last_error is None
