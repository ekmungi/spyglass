"""GET /privacy/outbound: exactly what is sent where, from the real code paths."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.radar import assess
from spyglass_service.radar.api import privacy as privacy_api
from spyglass_service.radar.assist import secrets_store
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.privacy import scrub

from .test_assess_support import add_item, make_engine, set_state

FAKE_KEY = "fake-or-key-55aa66bb77"


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _client(engine, settings: Settings) -> TestClient:
    """A small app with only the privacy router."""
    app = FastAPI()
    app.include_router(privacy_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings = engine, settings
    return TestClient(app)


def _settings(monkeypatch, tmp_path, **overrides) -> Settings:
    """Settings with a fake OpenRouter key and no keyring access."""
    monkeypatch.setenv("SPYGLASS_OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setattr(secrets_store, "get_secret", lambda engine_id: None)
    return Settings(_env_file=None, data_dir=tmp_path / "d", **overrides)


def _liked(engine, title: str) -> None:
    """A saved item judged into the health section."""
    item_id = add_item(engine, title)
    set_state(engine, item_id, vote="more")
    with Session(engine) as session:
        session.add(Assessment(item_id=item_id, section="health", tier="notable", score=70))
        session.commit()


def test_outbound_shows_the_exact_profile_block_the_judge_sends(engine, monkeypatch, tmp_path) -> None:
    """The block equals the judge's own block after the scrub, examples included."""
    settings = _settings(monkeypatch, tmp_path, privacy_send_examples=True)
    _liked(engine, "A liked article about polyp detection AI")
    body = _client(engine, settings).get("/api/radar/privacy/outbound").json()
    judge = assess.make_judge(engine, settings, llm=lambda *a: {})
    assert body["profile_block"] == scrub(judge.block, settings)
    assert body["example_titles"] == {"liked": ["A liked article about polyp detection AI"],
                                      "disliked": []}
    assert body["model_provider"]["host"] == "openrouter.ai"
    assert FAKE_KEY not in str(body)


def test_outbound_with_examples_off_sends_none(engine, monkeypatch, tmp_path) -> None:
    """Switch off: no titles listed and none in the block."""
    settings = _settings(monkeypatch, tmp_path, privacy_send_examples=False)
    _liked(engine, "A liked article about polyp detection AI")
    body = _client(engine, settings).get("/api/radar/privacy/outbound").json()
    assert body["example_titles"] == {"liked": [], "disliked": []}
    assert "polyp detection" not in body["profile_block"]
    assert body["switches"]["privacy_send_examples"]["on"] is False


def test_outbound_lists_destinations_and_switches(engine, monkeypatch, tmp_path) -> None:
    """Every destination row has the agreed fields; the switches carry plain descriptions."""
    settings = _settings(monkeypatch, tmp_path)
    body = _client(engine, settings).get("/api/radar/privacy/outbound").json()
    rows = {d["key"]: d for d in body["destinations"]}
    for row in rows.values():
        assert {"name", "host", "purpose", "what_is_sent", "carries_secret", "enabled"} <= set(row)
    assert rows["openrouter"]["carries_secret"] is True and rows["openrouter"]["enabled"] is True
    assert rows["jina"]["enabled"] is False and rows["slack"]["enabled"] is False
    assert rows["pages"]["host"] == "any public website"
    assert set(body["switches"]) == {"privacy_send_examples", "privacy_proxy_images",
                                     "jina_enabled", "privacy_allow_bot_checks"}
    assert "never anything personal" in body["switches"]["privacy_allow_bot_checks"]["description"]
    # On by default: the built-in browser may complete a site's automated check.
    assert body["switches"]["privacy_allow_bot_checks"]["on"] is True


def test_outbound_refuses_cross_site_requests(engine, monkeypatch, tmp_path) -> None:
    """A page on another site cannot read it."""
    client = _client(engine, _settings(monkeypatch, tmp_path))
    response = client.get("/api/radar/privacy/outbound", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
