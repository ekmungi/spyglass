"""Regression tests: the watch sweep runs once a day (unless the reader forces it), and the
five-minute capture poll and the cycle's Gmail and Slack collectors never run at once."""

import threading
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from spyglass_service.models import RunLog
from spyglass_service.radar.models import RadarDoc, dumps
from spyglass_service.radar.scheduler import RadarScheduler
from spyglass_service.radar.sources import COLLECTORS, WATCH_DOC, collect_all
from spyglass_service.radar.sources._common import capture_sources_lock

from .test_sources_support import make_engine, make_settings


def _runners(calls: list[str], **overrides):
    """Collectors that only record that they ran."""
    def runner(key):
        def run(_engine, _settings):
            calls.append(key)
            return 1, "1 new"
        return run

    table = {key: runner(key) for key in COLLECTORS}
    table.update(overrides)
    return table


def _set_last_sweep(engine, when: datetime) -> None:
    """Pretend the last successful sweep happened at `when`."""
    with Session(engine) as session:
        session.add(RadarDoc(key=WATCH_DOC, body=dumps({"last_ok_at": when.isoformat()})))
        session.commit()


def test_the_watch_sweep_runs_once_a_day(tmp_path) -> None:
    """A second cycle within 20 hours skips the sweep and logs why; a later one runs it."""
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        collect_all(engine, make_settings(), runners=_runners(calls))
        assert calls.count("watch") == 1
        counts = collect_all(engine, make_settings(), runners=_runners(calls))
        assert calls.count("watch") == 1 and counts["watch"] == 0
        with Session(engine) as session:
            last = session.exec(select(RunLog).where(RunLog.source == "radar:watch")
                                .order_by(RunLog.id.desc())).first()
        assert last.status == "skipped" and "once a day" in last.detail
        with Session(engine) as session:
            session.delete(session.get(RadarDoc, WATCH_DOC))
            session.commit()
        _set_last_sweep(engine, datetime.now(UTC) - timedelta(hours=21))
        collect_all(engine, make_settings(), runners=_runners(calls))
        assert calls.count("watch") == 2
    finally:
        engine.dispose()


def test_a_failed_sweep_is_retried_at_the_next_cycle(tmp_path) -> None:
    """Only a successful sweep counts as the day's sweep."""
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []

        def boom(_engine, _settings):
            calls.append("watch")
            raise RuntimeError("search down")

        collect_all(engine, make_settings(), runners=_runners(calls, watch=boom))
        collect_all(engine, make_settings(), runners=_runners(calls))
        assert calls.count("watch") == 2
    finally:
        engine.dispose()


def test_the_reader_can_force_the_sweep(tmp_path) -> None:
    """force_watch runs the sweep even when it ran an hour ago."""
    engine = make_engine(tmp_path)
    try:
        _set_last_sweep(engine, datetime.now(UTC) - timedelta(hours=1))
        calls: list[str] = []
        collect_all(engine, make_settings(), runners=_runners(calls))
        assert "watch" not in calls
        collect_all(engine, make_settings(), runners=_runners(calls), force_watch=True)
        assert calls.count("watch") == 1
    finally:
        engine.dispose()


def test_collectors_wait_for_a_running_capture_poll(tmp_path) -> None:
    """Gmail and Slack in a cycle do not start while the capture poll holds the lock."""
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []
        released = threading.Event()
        order: list[str] = []

        def slack(_engine, _settings):
            order.append("slack" if released.is_set() else "slack-too-early")
            return 0, "0"

        assert capture_sources_lock.acquire(timeout=1)

        def release_later():
            threading.Event().wait(0.3)
            released.set()
            capture_sources_lock.release()

        threading.Thread(target=release_later).start()
        collect_all(engine, make_settings(), runners=_runners(calls, slack=slack))
        assert order == ["slack"]
    finally:
        released.wait(2)
        engine.dispose()


def test_the_capture_poll_skips_while_a_collector_holds_the_lock(tmp_path) -> None:
    """The poll does not run on top of a cycle's Gmail or Slack collection."""
    engine = make_engine(tmp_path)
    try:
        scheduler = RadarScheduler(engine, make_settings(), lambda: object(), stages={})
        assert capture_sources_lock.acquire(timeout=1)
        try:
            assert scheduler.poll_captures() == {}
        finally:
            capture_sources_lock.release()
    finally:
        engine.dispose()


def test_collect_now_can_force_the_watch_sweep(tmp_path) -> None:
    """The scheduler hands the reader's force flag to the radar collectors."""
    engine = make_engine(tmp_path)
    try:
        seen: list[bool] = []
        holder: dict = {}
        names = ("legacy", "raindrop", "embed", "pipeline", "watch", "compose")
        stages = {n: (lambda: None) for n in names}
        stages["radar"] = lambda: seen.append(holder["s"].forcing_watch)
        scheduler = RadarScheduler(engine, make_settings(), lambda: object(), stages=stages)
        holder["s"] = scheduler
        assert scheduler.start_cycle_in_background("manual", force_watch=True)
        for _ in range(100):
            if seen and not scheduler.running:
                break
            threading.Event().wait(0.02)
        scheduler.run_cycle("schedule")
        assert seen == [True, False]
    finally:
        engine.dispose()


def test_the_collect_endpoint_forces_the_sweep_only_when_asked(tmp_path) -> None:
    """POST /collect leaves the daily rule alone; ?force_watch=true asks for the sweep."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spyglass_service.radar.api import sources as sources_api

    calls: list[dict] = []

    def start(trigger, **kwargs):
        calls.append(kwargs)
        return True

    engine = make_engine(tmp_path)
    try:
        app = FastAPI()
        app.include_router(sources_api.router)
        app.state.engine, app.state.settings = engine, make_settings()
        app.state.radar_scheduler = SimpleNamespace(start_cycle_in_background=start)
        with TestClient(app) as client:
            assert client.post("/collect").status_code == 200
            assert client.post("/collect?force_watch=true").status_code == 200
        assert calls == [{}, {"force_watch": True}]
    finally:
        engine.dispose()
