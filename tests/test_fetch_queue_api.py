"""Tests for the queued fetch API contract.

POST /fulltext no longer runs the acquisition ladder inside the request -- it enqueues and
returns the job. GET /fulltext carries the job state so the reader can render "fetching"
on a fresh mount, which is what makes progress survive navigating away.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.fetch_queue import job_for_card
from spyglass_service.models import Card, CardState, Item


@pytest.fixture()
def client_no_worker(tmp_path: Path):
    """TestClient seeded with one card, whose fetch worker never runs.

    The queue's own drain behaviour is covered in test_fetch_worker.py; holding the
    worker still here keeps these API assertions deterministic (a live worker would
    race the test to the job's terminal state).
    """
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, skip_startup_embed=True, skip_fetch_worker=True)
    with TestClient(app) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            item = Item(
                source="test",
                external_id="q1",
                title="Test Article",
                url="https://example.test/article",
                summary="A blurb.",
            )
            session.add(item)
            session.flush()
            session.add(Card(item_id=item.id, state=CardState.NEW, summary=""))
            session.commit()
        yield client


def test_post_fulltext_queues_the_job_instead_of_running_it_inline(client_no_worker):
    """The contract change: the response is a job, not an enrichment result."""
    r = client_no_worker.post("/api/cards/1/fulltext")

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["card_id"] == 1
    assert isinstance(body["job_id"], int)
    # The old synchronous contract returned the enrichment result; it must be gone, or a
    # stale frontend cast would keep "type-checking" against a shape that never arrives.
    assert "summary" not in body


def test_post_fulltext_twice_queues_a_single_job(client_no_worker):
    """Double-clicking the reader's button must not fetch the same article twice."""
    first = client_no_worker.post("/api/cards/1/fulltext").json()
    second = client_no_worker.post("/api/cards/1/fulltext").json()

    assert second["job_id"] == first["job_id"]


def test_post_fulltext_unknown_card_is_404_and_queues_nothing(client_no_worker):
    """Unknown cards keep their 404 -- the check moves ahead of the enqueue."""
    r = client_no_worker.post("/api/cards/9999/fulltext")

    assert r.status_code == 404
    assert job_for_card(client_no_worker.app.state.engine, card_id=9999) is None


def test_get_fulltext_reports_the_in_flight_job(client_no_worker):
    """What lets the reader show "fetching" after the pane was destroyed and rebuilt."""
    client_no_worker.post("/api/cards/1/fulltext")

    body = client_no_worker.get("/api/cards/1/fulltext").json()

    assert body["status"] == "absent"  # nothing stored yet
    assert body["job"]["status"] == "queued"


def test_get_fulltext_has_no_job_when_none_was_requested(client_no_worker):
    """A card nobody fetched reports no job rather than a fabricated idle one."""
    body = client_no_worker.get("/api/cards/1/fulltext").json()

    assert body["job"] is None


def test_active_fetch_jobs_lists_cards_with_work_in_flight(client_no_worker):
    """Drives the list-row pending marker without fattening the /api/cards payload."""
    assert client_no_worker.get("/api/fetch-jobs/active").json() == {"card_ids": []}

    client_no_worker.post("/api/cards/1/fulltext")

    assert client_no_worker.get("/api/fetch-jobs/active").json() == {"card_ids": [1]}
