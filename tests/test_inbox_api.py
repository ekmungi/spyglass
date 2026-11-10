"""Tests for the paper inbox API and MCP tools."""

from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.mcp_server import ServiceState, build_mcp


def make_app(tmp_path: Path, opened: list, channel: str = "#paper-inbox"):
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", vault_path=vault, inbox_channel=channel
    )
    return create_app(settings, link_opener=opened.append), settings


@pytest.fixture
def state(tmp_path: Path) -> ServiceState:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", inbox_channel="paper-inbox")
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    return ServiceState(settings=settings, engine=engine)


async def call(state: ServiceState, tool: str, **kwargs):
    async with Client(build_mcp(state)) as client:
        result = await client.call_tool(tool, kwargs)
    return result.data if result.data is not None else result.structured_content


async def test_a_session_runs_the_inbox_through_mcp(state: ServiceState) -> None:
    run = await call(state, "inbox_start")
    assert run["channel"] == "paper-inbox" and run["since"] is None
    # The workflow travels with the tool, so the inbox works without the skill in the vault.
    assert f"this is run {run['run_id']}" in run["instructions"]
    assert "## Debrief template" in run["instructions"]
    assert not run["instructions"].startswith("---")
    added = await call(
        state, "inbox_add_paper", run_id=run["run_id"], url="https://arxiv.org/abs/2410.00002",
        message_text="for Spyglass", message_ts="1.5",
    )
    filed = await call(
        state, "inbox_file_paper", entry_id=added["entry_id"], title="Agents paper",
        summary="It does X.", note_path="Papers/Agents paper.md", full_text=True,
    )
    assert filed == {"card_id": added["card_id"]}
    done = await call(state, "inbox_finish", run_id=run["run_id"], ok=True, watermark="1.5")
    assert done["status"] == "ok"
    assert (await call(state, "inbox_start"))["since"] == "1.5"


async def test_inbox_start_needs_a_channel(state: ServiceState) -> None:
    state.settings.inbox_channel = ""
    assert (await call(state, "inbox_start"))["error"] == "no_channel"


async def test_unknown_ids_come_back_as_errors(state: ServiceState) -> None:
    assert (await call(state, "inbox_file_paper", entry_id=42))["error"] == "not_found"
    assert (await call(state, "inbox_finish", run_id=42, ok=True))["error"] == "not_found"


def test_the_inbox_tab_lists_papers_and_opens_notes(tmp_path: Path) -> None:
    from spyglass_service.inbox import add_paper, file_paper, start_run

    opened: list[str] = []
    app, settings = make_app(tmp_path, opened)
    with TestClient(app) as client:
        engine = app.state.engine
        run = start_run(engine)
        added = add_paper(engine, run["run_id"], "https://example.org/p", message_text="hi")
        empty = client.post(f"/api/inbox/{added['card_id']}/open-note")
        assert empty.status_code == 404
        file_paper(engine, added["entry_id"], title="P", summary="s", note_path="Papers/P.md")
        body = client.get("/api/inbox").json()
        assert body["channel"] == "paper-inbox"
        assert body["papers"][0]["title"] == "P"
        response = client.post(f"/api/inbox/{added['card_id']}/open-note")
    assert response.status_code == 200
    assert opened[-1].startswith("obsidian://open?path=")
    # The note's absolute path, in the system's own separators (backslashes on Windows).
    path = Path(unquote(opened[-1].split("path=", 1)[1]))
    assert path.parts[-2:] == ("Papers", "P.md") and path.is_absolute()


def test_open_note_stays_inside_the_vault_and_reports_failures(tmp_path: Path) -> None:
    from spyglass_service.inbox import add_paper, file_paper, start_run

    opened: list[str] = []
    app, settings = make_app(tmp_path, opened)
    with TestClient(app) as client:
        engine = app.state.engine
        run = start_run(engine)
        outside = add_paper(engine, run["run_id"], "https://example.org/a")
        file_paper(engine, outside["entry_id"], note_path="../elsewhere/secret.md")
        assert client.post(f"/api/inbox/{outside['card_id']}/open-note").status_code == 403
        inside = add_paper(engine, run["run_id"], "https://example.org/b")
        file_paper(engine, inside["entry_id"], note_path="Papers/B.md")

        def broken(url: str) -> None:
            raise OSError("no handler")

        app.state.link_opener = broken
        response = client.post(f"/api/inbox/{inside['card_id']}/open-note")
    assert response.status_code == 502
    assert opened == []


async def test_a_session_saves_the_run_debrief(tmp_path: Path) -> None:
    """The run debrief is a vault note written by Spyglass, path kept on the run."""
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault, inbox_channel="c")
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    st = ServiceState(settings=settings, engine=engine)
    run = await call(st, "inbox_start")
    saved = await call(
        st, "inbox_save_debrief", run_id=run["run_id"], title="Inbox debrief 2026-10-14 08:10",
        markdown="## How they connect\n- [[A]] and [[B]] share grounding.",
    )
    note = Path(saved["path"])
    assert note.is_file() and vault in note.parents
    assert "share grounding" in note.read_text(encoding="utf-8")
    assert (await call(st, "inbox_save_debrief", run_id=999, title="t", markdown="m"))["error"] == "not_found"
    from spyglass_service.inbox_debrief import recent_debriefs

    [listed] = recent_debriefs(engine)
    assert listed["run_id"] == run["run_id"] and listed["debrief_path"] == str(note)


def test_the_inbox_tab_opens_a_run_debrief(tmp_path: Path) -> None:
    from spyglass_service.inbox import finish_run, start_run
    from spyglass_service.inbox_debrief import save_run_debrief

    opened: list[str] = []
    app, settings = make_app(tmp_path, opened)
    with TestClient(app) as client:
        engine = app.state.engine
        run = start_run(engine)
        assert client.post(f"/api/inbox/runs/{run['run_id']}/open-debrief").status_code == 404
        save_run_debrief(engine, settings, run["run_id"], "Inbox debrief", "## How they connect")
        finish_run(engine, run["run_id"], ok=True, watermark="1.0")
        later = start_run(engine)
        finish_run(engine, later["run_id"], ok=True, watermark="2.0")
        body = client.get("/api/inbox").json()
        assert body["last_run"]["debrief_path"] is None
        assert body["debriefs"][0]["run_id"] == run["run_id"]
        response = client.post(f"/api/inbox/runs/{run['run_id']}/open-debrief")
    assert response.status_code == 200
    assert opened[-1].startswith("obsidian://open?path=")
