"""Tests for the content REST API: GET /fulltext (reader) and POST /fulltext (queued fetch).

POST enqueues a job and returns immediately rather than running the enrichment
cascade inside the request. These tests therefore cover the path all the
way THROUGH the background worker -- POST, then wait for the job to finish -- which is
strictly more coverage than the old synchronous assertions had. The queue mechanics
themselves live in test_fetch_queue*.py.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.fetch_queue import TERMINAL_STATUSES, job_for_card
from spyglass_service.models import Card, CardState, Item


def _wait_for_terminal_job(engine, card_id: int, timeout: float = 10.0) -> str:
    """Poll until the card's fetch job finishes; return its terminal status.

    The worker runs on its own thread, so the assertions after a POST have to wait for it
    rather than assume the work happened inline.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = job_for_card(engine, card_id)
        if job is not None and job.status in TERMINAL_STATUSES:
            return job.status
        time.sleep(0.02)
    raise AssertionError(f"fetch job for card {card_id} never reached a terminal state")


def _make_client(tmp_path: Path) -> TestClient:
    """Build a TestClient for the Spyglass app with startup embed disabled (avoids threadpool races).

    Args:
        tmp_path: Pytest temp directory used to isolate DB and data files per test.

    Returns:
        An httpx/starlette TestClient whose lifespan is entered on __enter__.
    """
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


@pytest.fixture()
def client_with_card(tmp_path: Path):
    """TestClient over an app seeded with one Item (id=1) and one Card (id=1).

    Yields:
        Active TestClient (lifespan entered); card has id=1 and item url set.
    """
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            item = Item(
                source="test",
                external_id="t1",
                title="Test Article",
                url="https://example.test/article",
                summary="A blurb.",
            )
            session.add(item)
            session.flush()
            card = Card(item_id=item.id, state=CardState.NEW, summary="")
            session.add(card)
            session.commit()
        yield client


# ---------------------------------------------------------------------------
# POST /api/cards/{card_id}/fulltext
# ---------------------------------------------------------------------------


@pytest.mark.live_fetch_worker
def test_post_fulltext_queues_work_that_the_worker_then_enriches(client_with_card, monkeypatch):
    """The wiring end to end: POST enqueues, the worker runs enrich_item with bypass_gate.

    enrich_item is patched where the default runner looks it up (app), so the test never
    hits the network or an LLM. Asserts the deliberate click still bypasses the Gate-1
    relevance cutoff, which was the point of the old synchronous endpoint.
    """
    import spyglass_service.app as app_module

    calls: list[dict] = []

    def fake_enrich(engine, index, settings, card_id, *, bypass_gate=False):
        calls.append({"card_id": card_id, "bypass_gate": bypass_gate})
        return {"relevance_score": 88, "recommended": True, "summary": "Fresh", "category": "AI"}

    monkeypatch.setattr(app_module, "enrich_item", fake_enrich)

    r = client_with_card.post("/api/cards/1/fulltext")
    assert r.status_code == 202
    assert r.json()["status"] == "queued"

    engine = client_with_card.app.state.engine
    assert _wait_for_terminal_job(engine, card_id=1) == "done"
    assert calls == [{"card_id": 1, "bypass_gate": True}]


def test_post_fulltext_returns_404_for_unknown_card(client_with_card):
    """An unknown card is rejected before anything is queued.

    The 404 used to fall out of enrich_item returning None; with the work deferred the
    endpoint checks the card itself, so this stays a 404 rather than a queued job that
    fails later.
    """
    r = client_with_card.post("/api/cards/9999/fulltext")
    assert r.status_code == 404
    assert job_for_card(client_with_card.app.state.engine, card_id=9999) is None


@pytest.mark.live_fetch_worker
def test_post_fulltext_manual_trigger_reaches_conductor_with_settings_and_engine(
    client_with_card, monkeypatch
):
    """End-to-end (mocked): the manual button (POST /fulltext) routes through
    the REAL enrich_item (not monkeypatched here, unlike the tests above) down to
    documents.fetch_fulltext, and must arrive with the app's settings + engine attached --
    this is what activates the full ladder (Jina/browser toggles) + per-domain cache on
    the bypass_gate path, not just the automatic pass. Only fetch_fulltext itself and the
    LLM call are stubbed (no live network); a structured failure record still gets
    stored via the real store_fulltext call inside enrich_item.
    """
    import spyglass_service.enrich as enrich_module
    import spyglass_service.openrouter as openrouter_module

    captured = {}

    def spy_fetch_fulltext(url, *, settings=None, engine=None):
        captured["settings"] = settings
        captured["engine"] = engine
        # Simulate the ladder giving up -- a structured failure record.
        return {
            "markdown": "", "status": "failed", "content_type": "",
            "error": "blocked at T0 (HTTP 403)", "source_url": url,
            "detected_type": "html", "tier_reached": "T0",
            "http_status": 403, "error_class": "blocked",
        }

    monkeypatch.setattr(enrich_module, "fetch_fulltext", spy_fetch_fulltext)
    # bypass_gate=True skips Gate 1 entirely (no LLM call before the fetch);
    # the fetch fails, so Gate 2 never runs either -- no LLM call needed in this test.
    monkeypatch.setattr(
        openrouter_module, "chat_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    r = client_with_card.post("/api/cards/1/fulltext")
    assert r.status_code == 202

    engine = client_with_card.app.state.engine
    settings = client_with_card.app.state.settings
    # The ladder runs on the worker, so wait for the job before asserting
    # on what reached the conductor.
    assert _wait_for_terminal_job(engine, card_id=1) == "done"
    assert captured["engine"] is engine
    assert captured["settings"] is settings

    # The structured failure record was stored via the real enrich_item -> store_fulltext.
    from spyglass_service.content_store import get_fulltext

    stored = get_fulltext(engine, 1)
    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["error_class"] == "blocked"
    assert stored["tier_reached"] == "T0"
    assert stored["http_status"] == 403
