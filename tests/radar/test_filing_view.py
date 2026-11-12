"""Tests for the "To file" view extras and the brief's filing line
(radar/filing_view.py, radar/filing_summary.py)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_plan, filing_questions, filing_queue, filing_status
from spyglass_service.radar.filing_summary import filing_summary
from spyglass_service.radar.filing_view import (
    plan_view, questions_view, recent_view, status_line, status_view,
)
from spyglass_service.radar.models import Assessment, ItemExtra, dumps

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def background_unlocked(monkeypatch):
    """The developer unlock: without it no background run starts in this version."""
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")


@pytest.fixture
def env(tmp_path):
    """Three items, a vault with one project, UTC as the reader's zone."""
    (tmp_path / "vault" / "01 PROJECTS" / "Beta").mkdir(parents=True)
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        for n in (1, 2, 3):
            item = Item(source="rss", external_id=f"e{n}", title=f"Title {n}", url=f"https://x.example/{n}")
            session.add(item)
            session.commit()
            session.add(Assessment(item_id=item.id, headline=f"Headline **{n}**\nline", tier="top"))
            session.commit()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path / "vault",
                        radar_timezone="UTC", radar_filing_mode="auto")
    yield engine, settings
    engine.dispose()


def filed(engine, item_id: int, at: datetime, best_guess: bool = False) -> None:
    """Record a filing at a given time."""
    with Session(engine) as session:
        session.add(ItemExtra(item_id=item_id, data=dumps({"filed": {
            "path": f"03 RESOURCES/N{item_id}.md", "project": None, "at": at.isoformat(),
            "best_guess": best_guess}})))
        session.commit()


def test_the_status_line_for_each_state(env):
    engine, settings = env
    state = filing_status.read_status(engine)
    off = settings.model_copy(update={"radar_filing_mode": "off"})
    assert status_line("off", state, off, NOW).startswith("Background filing is off")
    assert "quiet for 10 minutes" in status_line("auto", state, settings, NOW)
    run = filing_status.begin_run(engine, mode="auto", kind="file", model="m", item_ids=[],
                                  now=NOW - timedelta(minutes=3))
    assert "running now" in status_line("auto", filing_status.read_status(engine), settings, NOW)
    filing_status.finish_run(engine, run["run_id"], result="stopped",
                             reason="obsidian_unreachable", now=NOW - timedelta(minutes=1))
    line = status_line("auto", filing_status.read_status(engine), settings, NOW)
    assert "stopped today 08:59: Obsidian was closed." in line and "Next try today 09:29" in line
    view = status_view(engine, settings, NOW)
    assert view["last_run"]["reason_text"] == "Obsidian was closed" and view["mode"] == "auto"


def test_questions_plan_and_recent_carry_clean_headlines(env):
    engine, settings = env
    filed(engine, 1, NOW - timedelta(days=1), best_guess=True)
    filed(engine, 2, NOW - timedelta(days=20))
    filing_questions.ask(engine, settings, 1, ["Beta"], now=NOW)
    filing_queue.enqueue(engine, 3)
    filing_plan.propose(engine, settings, 3, becomes="resource note", place="03 RESOURCES",
                        name="N3")
    [question] = questions_view(engine, NOW)
    assert question["headline"] == "Headline 1 line" and question["options"][-1] == "No project"
    [row] = plan_view(engine)
    assert row["headline"] == "Headline 3 line" and row["decision"] == "pending"
    [recent] = recent_view(engine, NOW)
    assert recent == {"item_id": 1, "headline": "Headline 1 line", "path": "03 RESOURCES/N1.md",
                      "project": None, "best_guess": True,
                      "at": (NOW - timedelta(days=1)).isoformat()}


def test_the_brief_line_says_nothing_when_nothing_happened(env):
    engine, settings = env
    assert filing_summary(engine, settings, NOW) is None


def test_the_brief_line_counts_yesterday_and_open_questions(env):
    engine, settings = env
    filed(engine, 1, NOW - timedelta(hours=12))
    filed(engine, 2, NOW - timedelta(hours=13))
    filing_questions.ask(engine, settings, 1, ["Beta"], now=NOW)
    summary = filing_summary(engine, settings, NOW)
    assert summary["line"] == "Filed yesterday: 2 items. 1 question is open."


def test_the_brief_line_points_out_a_stalled_run(env):
    engine, settings = env
    filing_queue.enqueue(engine, 3)
    run = filing_status.begin_run(engine, mode="auto", kind="file", model="m", item_ids=[3],
                                  now=NOW - timedelta(days=3))
    filing_status.finish_run(engine, run["run_id"], result="ok", now=NOW - timedelta(days=3))
    run = filing_status.begin_run(engine, mode="auto", kind="file", model="m", item_ids=[3],
                                  now=NOW - timedelta(hours=1))
    filing_status.finish_run(engine, run["run_id"], result="stopped",
                             reason="obsidian_unreachable", now=NOW - timedelta(hours=1))
    line = filing_summary(engine, settings, NOW)["line"]
    assert line == "Filing has not run since Monday: Obsidian was closed."
    off = settings.model_copy(update={"radar_filing_mode": "off"})
    assert filing_summary(engine, off, NOW) is None


def test_the_brief_line_mentions_a_waiting_plan(env):
    engine, settings = env
    filing_queue.enqueue(engine, 3)
    filing_plan.propose(engine, settings, 3, becomes="resource note", place="03 RESOURCES",
                        name="N3")
    assert filing_summary(engine, settings, NOW)["line"] == \
        "A filing plan of 1 item waits for your approval."


def test_the_today_payload_carries_the_filing_line(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spyglass_service.radar.api import briefs as briefs_api

    engine, settings = env
    app = FastAPI()
    app.include_router(briefs_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings = engine, settings
    client = TestClient(app)
    assert client.get("/api/radar/today").json()["filing"] is None
    filing_queue.enqueue(engine, 3)
    filing_plan.propose(engine, settings, 3, becomes="resource note", place="03 RESOURCES",
                        name="N3")
    assert client.get("/api/radar/today").json()["filing"]["plan"] == 1
