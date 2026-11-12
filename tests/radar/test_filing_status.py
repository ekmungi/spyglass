"""Tests for the background filing run's stored status (radar/filing_status.py)."""

from datetime import UTC, datetime, timedelta

import pytest

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar import filing_status as fs

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path):
    """An empty database."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine
    engine.dispose()


def test_a_fresh_database_reports_an_idle_run_that_never_ran(engine):
    status = fs.read_status(engine)
    assert status["state"] == "idle" and status["started_at"] is None
    assert status["failures"] == 0 and status["next_retry"] is None


def test_a_run_begins_with_a_token_and_only_that_token_is_current(engine):
    run = fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[3, 4], now=NOW)
    assert len(run["run_id"]) == 16 and run["state"] == "running"
    assert fs.current_run(engine, run["run_id"])["item_ids"] == [3, 4]
    assert fs.current_run(engine, "0" * 16) is None
    assert fs.current_run(engine, "not a token") is None


def test_an_ok_finish_clears_failures_and_the_retry_time(engine):
    run = fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[1], now=NOW)
    fs.finish_run(engine, run["run_id"], result="stopped", reason="obsidian_unreachable", now=NOW)
    run = fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[1], now=NOW)
    status = fs.finish_run(engine, run["run_id"], result="ok", filed=1, now=NOW)
    assert status["state"] == "idle" and status["failures"] == 0
    assert status["next_retry"] is None and status["filed"] == 1
    assert status["last_ran_at"] == NOW.isoformat()


def test_stops_wait_longer_each_time(engine):
    delays = []
    for _ in range(3):
        run = fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[], now=NOW)
        status = fs.finish_run(engine, run["run_id"], result="stopped", reason="failed", now=NOW)
        delays.append(datetime.fromisoformat(status["next_retry"]) - NOW)
    assert delays == [timedelta(minutes=30), timedelta(minutes=60), timedelta(minutes=120)]
    assert fs.retry_delay(50) == timedelta(hours=24)


def test_a_usage_limit_waits_until_its_reset_time(engine):
    reset = NOW + timedelta(hours=3)
    run = fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[], now=NOW)
    status = fs.finish_run(engine, run["run_id"], result="stopped", reason="usage_limit",
                           retry_at=reset, now=NOW)
    assert status["next_retry"] == reset.isoformat()


def test_a_report_is_kept_for_the_running_run_only(engine):
    run = fs.begin_run(engine, mode="plan_first", kind="plan", model="sonnet", item_ids=[], now=NOW)
    assert fs.record_report(engine, run["run_id"], "stopped", "skills_missing",
                            "vault-skills:ingest is not listed\nat all") == {"reported": True}
    assert fs.read_status(engine)["report"] == {
        "status": "stopped", "reason": "skills_missing", "detail": "vault-skills:ingest is not listed at all"}
    assert fs.record_report(engine, "f" * 16, "done", None, "")["error"] == "not_running"
    assert fs.record_report(engine, run["run_id"], "maybe", None, "")["error"] == "invalid_report"
    assert fs.record_report(engine, run["run_id"], "stopped", "bored", "")["error"] == \
        "invalid_report"


def test_a_run_left_running_by_a_crash_is_closed_as_crashed(engine):
    fs.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[], now=NOW)
    assert fs.recover_crashed(engine, now=NOW + timedelta(minutes=5)) is True
    status = fs.read_status(engine)
    assert (status["state"], status["result"], status["reason"]) == ("idle", "stopped", "crashed")
    assert fs.recover_crashed(engine, now=NOW) is False


def test_every_stop_reason_has_a_plain_sentence():
    for code in fs.STOP_REASONS:
        assert fs.reason_text(code)[0].isupper()
    assert fs.reason_text("unknown") == fs.reason_text("failed")
