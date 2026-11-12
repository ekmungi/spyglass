"""Tests for the usage report and its HTTP endpoint."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar import usage, usage_report
from spyglass_service.radar.api import usage as usage_api
from spyglass_service.radar.models import AssistThread, utcnow


@pytest.fixture
def db(tmp_path):
    """A fresh database with every table, disposed afterwards."""
    engine = create_db_engine(tmp_path / "r.db")
    init_db(engine)
    yield engine
    engine.dispose()


def add(db, *, age_days=0.0, purpose="chat", provider="claude_code", model="haiku", i=None, w=None,
        r=None, o=None, cost=None, thread_id=None) -> None:
    """Insert one usage row `age_days` old."""
    with Session(db) as session:
        session.add(usage.UsageCall(
            at=utcnow() - timedelta(days=age_days), purpose=purpose, provider=provider, model=model,
            input_tokens=i, cache_write_tokens=w, cache_read_tokens=r, output_tokens=o,
            cost_usd=cost, thread_id=thread_id))
        session.commit()


def test_an_empty_table_reports_zeros(db):
    report = usage_report.build_report(db, days=7)
    assert report["totals"]["calls"] == 0 and report["totals"]["cached_share"] is None
    assert report["per_day"] == [] and report["by_purpose"] == [] and report["conversations"] == []


def test_totals_sum_the_figures_and_the_cached_share_is_read_over_the_prompt(db):
    add(db, i=10, w=100, r=900, o=50, cost=0.01)
    add(db, i=10, w=0, r=990, o=30, cost=0.02, purpose="triage")
    totals = usage_report.build_report(db, days=7)["totals"]
    assert totals["calls"] == 2 and totals["input_tokens"] == 20 and totals["cache_read_tokens"] == 1890
    assert totals["output_tokens"] == 80 and totals["context_tokens"] == 2010
    assert totals["cached_share"] == pytest.approx(1890 / 2010)
    assert totals["cost_usd"] == pytest.approx(0.03)


def test_calls_without_figures_are_counted_but_add_nothing(db):
    add(db, i=None, w=None, r=None, o=None)
    add(db, i=5, w=0, r=0, o=5)
    totals = usage_report.build_report(db, days=7)["totals"]
    assert totals["calls"] == 2 and totals["unreported_calls"] == 1 and totals["input_tokens"] == 5


def test_rows_older_than_the_window_are_left_out(db):
    add(db, age_days=1, i=1, o=1)
    add(db, age_days=30, i=100, o=100)
    assert usage_report.build_report(db, days=7)["totals"]["input_tokens"] == 1
    assert usage_report.build_report(db, days=90)["totals"]["input_tokens"] == 101


def test_rows_group_by_day_by_purpose_and_by_model(db):
    add(db, age_days=0, purpose="chat", model="haiku", i=1, r=9, o=1)
    add(db, age_days=2, purpose="triage", model="haiku", i=2, r=8, o=2)
    add(db, age_days=2, purpose="triage", model="sonnet", i=3, r=7, o=3)
    report = usage_report.build_report(db, days=7)
    assert len(report["per_day"]) == 2 and report["per_day"][0]["day"] < report["per_day"][1]["day"]
    assert {(p["purpose"], p["calls"]) for p in report["by_purpose"]} == {("chat", 1), ("triage", 2)}
    assert {(m["purpose"], m["model"]) for m in report["by_model"]} == {
        ("chat", "haiku"), ("triage", "haiku"), ("triage", "sonnet")}


def test_the_most_expensive_conversations_come_first_and_at_most_ten(db):
    with Session(db) as session:
        for n in range(12):
            session.add(AssistThread(title=f"Thread {n}", item_id=n))
        session.commit()
    for n in range(12):
        add(db, thread_id=n + 1, i=1, w=1, r=1, o=1, cost=0.01 * (n + 1))
    add(db, thread_id=12, i=1, w=1, r=1, o=1, cost=0.5)
    rows = usage_report.build_report(db, days=7)["conversations"]
    assert len(rows) == 10 and rows[0]["thread_id"] == 12 and rows[0]["turns"] == 2
    assert rows[0]["title"] == "Thread 11" and rows[0]["item_id"] == 11
    assert [r["thread_id"] for r in rows][1:3] == [11, 10]


def test_conversations_without_a_reported_cost_rank_by_tokens(db):
    with Session(db) as session:
        session.add(AssistThread(title="small"))
        session.add(AssistThread(title="big"))
        session.commit()
    add(db, thread_id=1, i=10, w=0, r=0, o=10)
    add(db, thread_id=2, i=10, w=5000, r=0, o=10)
    assert [r["title"] for r in usage_report.build_report(db, days=7)["conversations"]] == ["big", "small"]


def test_days_are_validated():
    with pytest.raises(ValueError):
        usage_report.build_report(None, days=0)


def make_client(db) -> TestClient:
    """A small app with only the usage router."""
    app = FastAPI()
    app.state.engine = db
    app.include_router(usage_api.router, prefix="/api/radar")
    return TestClient(app)


def test_endpoint_returns_the_report(db):
    add(db, i=1, w=2, r=3, o=4)
    body = make_client(db).get("/api/radar/usage?days=7").json()
    assert body["days"] == 7 and body["totals"]["cache_read_tokens"] == 3


def test_endpoint_rejects_a_bad_window(db):
    client = make_client(db)
    assert client.get("/api/radar/usage?days=0").status_code == 422
    assert client.get("/api/radar/usage?days=9999").status_code == 422
    assert client.get("/api/radar/usage").json()["days"] == 7


def test_message_endpoint_returns_the_turns_figures(db):
    add(db, thread_id=1, i=2, w=100, r=900, o=40, cost=0.01)
    with Session(db) as session:
        row = session.exec(select(usage.UsageCall)).first()
        row.message_id = 55
        session.add(row)
        session.commit()
    body = make_client(db).get("/api/radar/usage/messages/55").json()
    assert body["cache_read_tokens"] == 900 and body["context_tokens"] == 1002
    assert body["cached_share"] == pytest.approx(900 / 1002)


def test_message_endpoint_is_404_for_a_message_without_figures(db):
    assert make_client(db).get("/api/radar/usage/messages/9").status_code == 404


def test_message_endpoint_reports_a_condensed_turn_and_the_model(db):
    with Session(db) as session:
        session.add(usage.UsageCall(purpose="chat", provider="claude_code", model="haiku", message_id=7,
                                    input_tokens=1, output_tokens=1, condensed=True))
        session.commit()
    body = make_client(db).get("/api/radar/usage/messages/7").json()
    assert body["condensed"] is True and body["model"] == "haiku" and body["provider"] == "claude_code"
