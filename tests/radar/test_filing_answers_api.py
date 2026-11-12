"""Tests for the background run's API: the extended GET /filing, answers, plan approval and
opening a filed note (radar/api/filing.py and radar/api/filing_answers.py).

The opener is a fake; no application is opened and nothing is written into a vault.
"""

from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_plan, filing_questions, filing_queue
from spyglass_service.radar.api import filing as filing_api
from spyglass_service.radar.models import Assessment, ItemExtra, dumps


@pytest.fixture
def client(tmp_path):
    """A client for the filing router, two items (one filed), and a fake opener."""
    vault = tmp_path / "vault"
    (vault / "01 PROJECTS" / "Beta").mkdir(parents=True)
    (vault / "03 RESOURCES").mkdir(parents=True)
    (vault / "03 RESOURCES" / "N1.md").write_text("x", encoding="utf-8")
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        for n in (1, 2):
            item = Item(source="rss", external_id=f"e{n}", title=f"T{n}", url=f"https://x.example/{n}")
            session.add(item)
            session.commit()
            session.add(Assessment(item_id=item.id, headline=f"Headline {n}", tier="top"))
            session.commit()
        session.add(ItemExtra(item_id=1, data=dumps({"filed": {
            "path": "03 RESOURCES/N1.md", "project": None, "at": "2099-01-01T00:00:00+00:00",
            "best_guess": True}})))
        session.commit()
    opened: list[str] = []
    app = FastAPI()
    app.include_router(filing_api.router, prefix="/api/radar")
    app.state.engine = engine
    app.state.settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault,
                                  radar_filing_mode="auto")
    app.state.link_opener = opened.append
    yield TestClient(app), engine, app.state.settings, opened
    engine.dispose()


def test_get_filing_carries_status_questions_plan_and_recent(client, monkeypatch):
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")
    http, engine, settings, _opened = client
    filing_questions.ask(engine, settings, 1, ["Beta"])
    filing_queue.enqueue(engine, 2)
    filing_plan.propose(engine, settings, 2, becomes="resource note", place="03 RESOURCES",
                        name="N2")
    body = http.get("/api/radar/filing").json()
    assert body["count"] == 1 and body["status"]["mode"] == "auto"
    assert body["status"]["line"].startswith("Filing runs after the queue has been quiet")
    assert body["questions"][0]["options"] == ["Beta", "No project"]
    assert body["plan"][0]["item_id"] == 2 and body["recent"][0]["best_guess"] is True


def test_answers_are_submitted_in_one_go(client):
    http, engine, settings, _opened = client
    filing_questions.ask(engine, settings, 1, ["Beta"])
    question = filing_questions.open_questions(engine)[0]
    body = {"answers": [{"question_id": question["id"], "choice": "Beta"}]}
    assert http.post("/api/radar/filing/answers", json=body).json() == {"answered": 1}
    assert filing_questions.answered_unapplied(engine)[0]["project"] == "Beta"


def test_bad_answers_are_refused_and_nothing_is_stored(client):
    http, engine, settings, _opened = client
    filing_questions.ask(engine, settings, 1, ["Beta"])
    question = filing_questions.open_questions(engine)[0]
    bad = {"answers": [{"question_id": question["id"], "choice": "Gamma"}]}
    assert http.post("/api/radar/filing/answers", json=bad).status_code == 422
    assert http.post("/api/radar/filing/answers", json={"answers": []}).status_code == 422
    assert http.post("/api/radar/filing/answers", content="x",
                     headers={"content-type": "text/plain"}).status_code == 415
    cross = http.post("/api/radar/filing/answers", json=bad, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert len(filing_questions.open_questions(engine)) == 1


def test_the_plan_is_approved_with_struck_rows_in_one_go(client):
    http, engine, settings, _opened = client
    filing_queue.enqueue(engine, 2)
    filing_plan.propose(engine, settings, 2, becomes="resource note", place="03 RESOURCES",
                        name="N2")
    row = filing_plan.plan_rows(engine)[0]
    assert http.post("/api/radar/filing/plan/approve",
                     json={"approved": [], "struck": []}).status_code == 422
    assert http.post("/api/radar/filing/plan/approve",
                     json={"approved": [999], "struck": []}).status_code == 422
    assert http.post("/api/radar/filing/plan/approve",
                     json={"approved": [row["id"]], "struck": []}).json() == {"approved": 1,
                                                                             "struck": 0}
    assert filing_plan.approved_rows(engine)[0]["item_id"] == 2


def test_a_filed_note_opens_in_obsidian_from_its_recorded_path_only(client, tmp_path):
    http, _engine, _settings, opened = client
    assert http.post("/api/radar/filing/recent/1/open", json={}).json() == {"opened": True}
    assert opened and opened[0].startswith("obsidian://open?path=")
    assert unquote(opened[0]).endswith("N1.md")
    assert http.post("/api/radar/filing/recent/2/open", json={}).status_code == 404
