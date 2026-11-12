"""Filing is configuration: the vault skill names, the `configured` flag and what it switches off."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar import filing_trigger
from spyglass_service.radar.filing_config import (
    NOT_CONFIGURED, filing_configured, skill_names, valid_skill_name,
)
from spyglass_service.radar.filing_view import status_view

from .test_filing_api import add_item, make_app

SKILLS = {"radar_filing_ingest_skill": "vault-skills:ingest",
          "radar_filing_manage_skill": "vault-skills:manage"}


@pytest.fixture
def engine_and_path(tmp_path):
    """A fresh database engine and the test's folder."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine, tmp_path
    engine.dispose()


@pytest.fixture
def api_unconfigured(tmp_path):
    """The filing routes with a vault folder but no vault skill names set."""
    app, engine = make_app(tmp_path)
    app.state.settings = app.state.settings.model_copy(
        update={"radar_filing_ingest_skill": "", "radar_filing_manage_skill": ""})
    add_item(engine, 1)
    yield TestClient(app)
    engine.dispose()


@pytest.mark.parametrize("value, expected", [
    ("vault-skills:ingest", "vault-skills:ingest"), (" plain_skill ", "plain_skill"),
    ("", None), ("a:b:c", None), ("has space", None), ("x</y>", None), (None, None),
])
def test_skill_names_must_look_like_skill_names(value: object, expected: str | None) -> None:
    """Letters, digits, hyphen, underscore and at most one colon; anything else is None."""
    assert valid_skill_name(value) == expected


def test_configured_needs_a_vault_and_both_skill_names(tmp_path) -> None:
    """Missing vault, one missing name or the defaults: not configured."""
    assert not filing_configured(Settings(_env_file=None))
    assert not filing_configured(Settings(_env_file=None, **SKILLS))
    assert not filing_configured(Settings(_env_file=None, vault_path=tmp_path,
                                          radar_filing_ingest_skill="vault-skills:ingest"))
    assert filing_configured(Settings(_env_file=None, vault_path=tmp_path, **SKILLS))
    assert skill_names(Settings(_env_file=None)) == {"ingest": None, "manage": None}


def test_defaults_carry_no_plugin_or_skill_name() -> None:
    """The plugin and both skill names are empty unless the owner's environment sets them."""
    settings = Settings(_env_file=None)
    assert (settings.radar_filing_plugin, settings.radar_filing_ingest_skill,
            settings.radar_filing_manage_skill) == ("", "", "")


def test_status_carries_configured(engine_and_path) -> None:
    """`status.configured` follows the settings."""
    engine, tmp_path = engine_and_path
    assert status_view(engine, Settings(_env_file=None, data_dir=tmp_path))["configured"] is False
    on = Settings(_env_file=None, data_dir=tmp_path, vault_path=tmp_path, **SKILLS)
    assert status_view(engine, on)["configured"] is True


def test_trigger_never_starts_a_run_when_not_configured(engine_and_path) -> None:
    """An "auto" mode without skill names starts nothing, however much is queued."""
    from spyglass_service.radar import filing_queue
    from spyglass_service.radar.models import utcnow
    engine, tmp_path = engine_and_path
    filing_queue.enqueue(engine, 1)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", radar_filing_mode="auto",
                        vault_path=tmp_path)
    started: list[int] = []
    reason = filing_trigger.filing_tick(engine, settings, now=utcnow() + timedelta(hours=3),
                                        runner=lambda e, s: started.append(1), busy=lambda s: False)
    assert reason is None and started == []


def test_api_refuses_queueing_and_offers_no_session_when_not_configured(api_unconfigured) -> None:
    """409 with the plain sentence on queueing; open and preview answer available false."""
    client: TestClient = api_unconfigured
    res = client.post("/api/radar/items/1/file", json={})
    assert res.status_code == 409 and res.json()["detail"] == NOT_CONFIGURED
    for path in ("/api/radar/filing/open", "/api/radar/filing/preview"):
        body = client.post(path, json={}).json()
        assert body == {"available": False, "detail": NOT_CONFIGURED}
    assert client.get("/api/radar/filing").json()["status"]["configured"] is False
