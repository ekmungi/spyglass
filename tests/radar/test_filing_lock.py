"""Background filing is locked in this version, and the vault tool is configuration.

Without the developer unlock (`SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED`) no background run starts
and the view says so, whatever mode an earlier version stored. The vault tool's launcher name and
its look-up commands come only from the environment and are validated strictly.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar import filing_queue, filing_trigger
from spyglass_service.radar.filing_config import (
    BACKGROUND_UNAVAILABLE, BACKGROUND_UNAVAILABLE_LINE, background_unlocked, effective_mode,
    tool_commands, tool_name,
)
from spyglass_service.radar.filing_run import RunOptions, run_filing
from spyglass_service.radar.filing_view import status_view
from spyglass_service.radar.models import utcnow

from .test_filing_api import add_item, make_app

UNLOCK = "SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED"
SKILLS = {"radar_filing_ingest_skill": "vault-skills:ingest",
          "radar_filing_manage_skill": "vault-skills:manage"}


@pytest.fixture(autouse=True)
def locked(monkeypatch):
    """Every test starts locked and with no vault tool configured."""
    for name in (UNLOCK, "SPYGLASS_RADAR_FILING_TOOL", "SPYGLASS_RADAR_FILING_TOOL_COMMANDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def engine(tmp_path):
    """A fresh database with one queued item."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    add_item(engine, 1)
    filing_queue.enqueue(engine, 1)
    yield engine
    engine.dispose()


def stored_auto(tmp_path: Path) -> Settings:
    """Settings as an earlier version left them: filing set up and the mode stored as "auto"."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path,
                    radar_filing_mode="auto", **SKILLS)


@pytest.mark.parametrize("value, expected", [
    (None, False), ("", False), ("0", False), ("no", False), ("1", True), ("true", True),
    (" TRUE ", True), ("on", True)])
def test_the_unlock_is_read_from_the_environment(monkeypatch, value, expected) -> None:
    if value is not None:
        monkeypatch.setenv(UNLOCK, value)
    assert background_unlocked() is expected


def test_the_effective_mode_is_off_until_unlocked(tmp_path, monkeypatch) -> None:
    settings = stored_auto(tmp_path)
    assert effective_mode(settings) == "off"
    monkeypatch.setenv(UNLOCK, "1")
    assert effective_mode(settings) == "auto"


def test_the_trigger_never_starts_a_run_while_locked(engine, tmp_path) -> None:
    started: list[int] = []
    reason = filing_trigger.filing_tick(
        engine, stored_auto(tmp_path), now=utcnow() + timedelta(hours=3),
        runner=lambda e, s: started.append(1), busy=lambda s: False)
    assert reason is None and started == []


def test_the_trigger_starts_a_run_when_unlocked(engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(UNLOCK, "1")
    started: list[int] = []
    reason = filing_trigger.filing_tick(
        engine, stored_auto(tmp_path), now=utcnow() + timedelta(hours=3),
        runner=lambda e, s: started.append(1), busy=lambda s: False)
    assert reason is not None and started == [1]


def test_a_direct_call_into_the_runner_is_refused_while_locked(engine, tmp_path) -> None:
    launched: list[int] = []

    def launch(*args):
        launched.append(1)
        raise AssertionError("a locked run must never start a session")

    result = run_filing(engine, stored_auto(tmp_path), RunOptions(launch=launch))
    assert result == {"result": "stopped", "reason": "failed", "detail": BACKGROUND_UNAVAILABLE}
    forced = run_filing(engine, stored_auto(tmp_path), RunOptions(mode="plan_first", launch=launch))
    assert forced["reason"] == "failed" and launched == []
    assert BACKGROUND_UNAVAILABLE == "Background filing is not available in this version."


def test_the_runner_still_answers_off_for_the_off_mode(engine, tmp_path) -> None:
    off = stored_auto(tmp_path).model_copy(update={"radar_filing_mode": "off"})
    assert run_filing(engine, off) == {"result": "off"}


def test_the_status_reports_off_and_unavailable_while_locked(engine, tmp_path, monkeypatch) -> None:
    status = status_view(engine, stored_auto(tmp_path))
    assert status["mode"] == "off" and status["background_available"] is False
    assert status["line"] == BACKGROUND_UNAVAILABLE_LINE
    assert BACKGROUND_UNAVAILABLE_LINE == (
        "Background filing is not available in this version. Use File now.")
    monkeypatch.setenv(UNLOCK, "1")
    status = status_view(engine, stored_auto(tmp_path))
    assert status["mode"] == "auto" and status["background_available"] is True


def test_the_filing_route_reports_the_lock(tmp_path) -> None:
    app, api_engine = make_app(tmp_path)
    app.state.settings = app.state.settings.model_copy(update={"radar_filing_mode": "auto"})
    add_item(api_engine, 1)
    body = TestClient(app).get("/api/radar/filing").json()["status"]
    api_engine.dispose()
    assert body["mode"] == "off" and body["background_available"] is False
    assert body["line"] == BACKGROUND_UNAVAILABLE_LINE


@pytest.mark.parametrize("value, expected", [
    ("vault-tool", "vault-tool"), (" tool_1.sh ", "tool_1.sh"), ("", ""),
    ("a b", ""), ("../x", ""), ("a/b", ""), ("..", ""), ("x;rm", ""), ("a" * 65, "")])
def test_the_tool_name_is_validated_strictly(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL", value)
    assert tool_name() == expected


@pytest.mark.parametrize("value, expected", [
    ("", ()), ("lookup folder", ("lookup folder",)),
    (" lookup folder , lookup template ,lookup folder", ("lookup folder", "lookup template")),
    ("lookup  folder", ()), ("Lookup folder", ()), ("lookup folder; rm", ()),
    ("lookup folder, bad$x", ()), ("lookup folder,", ("lookup folder",)),
    ("lookup $(x)", ()), ("lookup 'a'", ())])
def test_the_look_up_commands_are_validated_strictly(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL_COMMANDS", value)
    assert tool_commands() == expected


def test_the_look_up_commands_default_to_none() -> None:
    assert tool_commands() == () and tool_name() == ""
