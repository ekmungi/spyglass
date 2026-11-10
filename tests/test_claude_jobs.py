"""Tests for background jobs: Prepare detail and File it as hidden Claude runs."""

import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import frontmatter
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlmodel import Session, select

from spyglass_service import claude_jobs as jobs
from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.detail_notes import (
    NoteNotRemovable,
    delete_detail_note,
    note_filename,
    write_detail_note,
)
from spyglass_service.job_worker import ClaudeJobWorker
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.models import Card, ClaudeJob, Item, RunLog

OK_RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "Done.",
             "num_turns": 7, "duration_ms": 41000, "total_cost_usd": 0.21,
             "usage": {"input_tokens": 1200, "output_tokens": 900}, "permission_denials": []}


OBSIDIAN = {"type": "http", "url": "http://127.0.0.1:27123/mcp/",
            "headers": {"Authorization": "Bearer ${OBSIDIAN_API_KEY}"}}


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch) -> Path:
    """Keep the tests away from the real ~/.claude.json."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture
def state(tmp_path: Path, fake_obsidian) -> ServiceState:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / ".mcp.json").write_text(json.dumps({"mcpServers": {"obsidian-vault": OBSIDIAN}}))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault,
                        claude_command="claude-test")
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    st = ServiceState(settings=settings, engine=engine)
    # Spyglass, not the run, asks Obsidian to move the note: tests use a stand-in.
    st.obsidian_move = fake_obsidian
    return st


def add_card(state: ServiceState, title: str = "Optogenetics, explained") -> int:
    with Session(state.engine) as session:
        item = Item(source="rss", external_id=title, title=title, url="https://x.test/a")
        session.add(item)
        session.commit()
        card = Card(item_id=item.id, summary=f"About {title}.")
        session.add(card)
        session.commit()
        return card.id


def call(state: ServiceState, tool: str, args: dict) -> dict:
    async def go():
        async with Client(build_mcp(state)) as client:
            result = await client.call_tool(tool, args)
            return result.structured_content
    return asyncio.run(go())


def card_note(state: ServiceState, card_id: int) -> str | None:
    with Session(state.engine) as session:
        return session.get(Card, card_id).briefing_path


def job_row(state: ServiceState, job_id: int) -> ClaudeJob:
    with Session(state.engine) as session:
        return session.get(ClaudeJob, job_id)


class FakeClaude:
    """Stands in for `claude -p`: runs a script of MCP calls, then prints a JSON result."""

    def __init__(self, state: ServiceState, script=None, result=None, **outcome) -> None:
        self.state, self.script, self.result, self.outcome = state, script, result, outcome
        self.commands: list[list[str]] = []
        self.cwd: Path | None = None

    def __call__(self, command, cwd, timeout_s, should_stop, prompt):
        self.commands.append(command)
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.prompt = prompt
        job_id = int(prompt.split()[3])
        if self.script:
            self.script(self.state, job_id, should_stop)
        result = OK_RESULT if self.result is None else self.result
        return jobs.RunOutcome(0, json.dumps(result) if result else "", "", **self.outcome)


def worker(state: ServiceState, run, probe=lambda url: True, opened=None) -> ClaudeJobWorker:
    return ClaudeJobWorker(state.engine, state.settings,
                           opener=(opened.append if opened is not None else lambda url: None),
                           run=run, probe=probe, sleep=lambda s: None)


def prepare_script(state, job_id, should_stop):
    start = call(state, "job_start", {"job_id": job_id})
    assert start["kind"] == "prepare-detail" and "job_save_detail" in start["instructions"]
    saved = call(state, "job_save_detail", {"job_id": job_id, "title": start["item"]["title"],
                                            "markdown": "Bottom line.\n\n## Key points\n- One"})
    assert saved["saved"] is True
    call(state, "job_finish", {"job_id": job_id, "ok": True, "message": "A note on optogenetics."})


# --- the command ---------------------------------------------------------------------------


def test_the_command_is_hidden_and_limited_to_the_jobs_tools(state: ServiceState) -> None:
    config = jobs.mcp_config_file(state.settings, 7790, jobs.PREPARE)
    cmd = jobs.build_command(state.settings, "claude", jobs.PREPARE, config)
    assert cmd[:2] == ["claude", "-p"]
    flags = {cmd[i]: cmd[i + 1] for i in range(2, len(cmd) - 1) if cmd[i].startswith("--")}
    assert flags["--output-format"] == "stream-json" and "--verbose" in cmd
    assert flags["--permission-mode"] == "dontAsk"
    # Claude Code's default on a Max plan is Opus; jobs name their model.
    assert flags["--model"] == "sonnet"
    # The user's and the vault's settings files are ignored, so their allow rules do not apply.
    assert flags["--setting-sources"] == ""
    tools = flags["--allowedTools"].split(",")
    assert "mcp__spyglass__job_save_detail" in tools
    # No file tool is allowed by name: a bare "Read" would allow reading outside the vault.
    assert not {"Read", "Glob", "Grep", "Write", "Edit", "Bash", "WebFetch"} & set(tools)
    denied = flags["--disallowedTools"].split(",")
    assert {"Bash", "Write", "Edit", "WebFetch", "WebSearch", "Task"} <= set(denied)
    assert "mcp__obsidian-vault__vault_delete" in denied
    # No argument carries quotes or JSON: an npm install's claude.cmd would mangle them.
    assert not any('"' in arg or "{" in arg for arg in cmd)
    servers = json.loads(Path(flags["--mcp-config"]).read_text())["mcpServers"]
    assert list(servers) == ["spyglass"] and servers["spyglass"]["url"].endswith(":7790/mcp/")
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert "job_start with job_id 7" in jobs.job_prompt(7, jobs.PREPARE, 42)


def test_a_filing_run_has_no_obsidian_tool_and_asks_spyglass_to_move(state: ServiceState) -> None:
    """The run asks Spyglass to move its note; it holds no Obsidian tool of its own."""
    config = jobs.mcp_config_file(state.settings, 7777, jobs.FILE)
    cmd = jobs.build_command(state.settings, "claude", jobs.FILE, config)
    tools = cmd[cmd.index("--allowedTools") + 1].split(",")
    denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "mcp__spyglass__job_file_note" in tools
    assert "mcp__spyglass__job_save_detail" not in tools
    assert not [tool for tool in tools if tool.startswith("mcp__obsidian")]
    # Denied by name as well, in case the server ever reaches a run.
    assert "mcp__obsidian-vault__vault_move" in denied
    assert "--strict-mcp-config" in cmd
    # Only Spyglass's own server is loaded, and the Obsidian server's login header is no longer
    # copied into a file for the run.
    text = config.read_text()
    assert list(json.loads(text)["mcpServers"]) == ["spyglass"]
    assert "Authorization" not in text and "OBSIDIAN_API_KEY" not in text


@pytest.mark.parametrize("kind", [jobs.PREPARE, jobs.FILE])
def test_a_run_gets_only_the_built_in_tools_it_needs(state: ServiceState, kind: str) -> None:
    """dontAsk refuses only tools that would need a permission prompt, and some built-in tools
    (scheduling, remote triggers, messages to other Claude sessions) need none. So the run's
    built-in tools are limited to reading and searching; Spyglass's MCP tools are not built-in."""
    config = jobs.mcp_config_file(state.settings, 7777, kind)
    cmd = jobs.build_command(state.settings, "claude", kind, config)
    assert cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep"


def test_the_obsidian_server_is_found_where_claude_keeps_it(
        state: ServiceState, _home: Path) -> None:
    vault = state.settings.vault_path
    (vault / ".mcp.json").unlink()
    with pytest.raises(jobs.ObsidianServerMissing, match="obsidian-vault"):
        jobs.find_obsidian_server(state.settings)
    user = {"type": "http", "url": "http://127.0.0.1:27123/mcp/"}
    (_home / ".claude.json").write_text(json.dumps({"mcpServers": {"obsidian-vault": user}}))
    assert jobs.find_obsidian_server(state.settings) == user
    local = {"type": "http", "url": "https://127.0.0.1:27124/mcp/"}
    (_home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"obsidian-vault": user},
        "projects": {vault.as_posix(): {"mcpServers": {"obsidian-vault": local}}}}))
    assert jobs.find_obsidian_server(state.settings) == local


def test_an_api_key_in_the_environment_is_not_passed_on(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    env = jobs.child_env()
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDECODE" not in env
    assert env["SOMETHING_ELSE"] == "kept"


def test_claude_is_found_from_the_setting_then_path_then_the_installer(
        state: ServiceState, monkeypatch, tmp_path: Path) -> None:
    assert jobs.find_claude(state.settings) == "claude-test"
    monkeypatch.setattr(jobs.shutil, "which", lambda name: f"/opt/{name}.cmd")
    assert jobs.find_claude(state.settings) == "/opt/claude-test.cmd"
    state.settings.claude_command = None
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "/usr/bin/claude")
    assert jobs.find_claude(state.settings) == "/usr/bin/claude"
    monkeypatch.setattr(jobs.shutil, "which", lambda name: None)
    assert jobs.find_claude(state.settings) is None
    exe = Path.home() / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert jobs.find_claude(state.settings) == str(exe)


# --- reading the run's result -----------------------------------------------------------------


def outcome(result=None, **kwargs) -> jobs.RunOutcome:
    stdout = json.dumps(result) if isinstance(result, dict) else (result or "")
    return jobs.RunOutcome(kwargs.pop("returncode", 0), stdout, kwargs.pop("stderr", ""), **kwargs)


@pytest.mark.parametrize(("result", "kwargs", "expected"), [
    (OK_RESULT, {}, None),
    ({**OK_RESULT, "is_error": True, "result": "Not logged in · Please run /login"}, {},
     "Claude stopped: Not logged in · Please run /login"),
    ({**OK_RESULT, "subtype": "error_max_turns"}, {}, "used all 40 turns"),
    ({**OK_RESULT, "is_error": True, "result": "x",
      "permission_denials": [{"tool_name": "Write"}, {"tool_name": "Bash"}]}, {},
     "Tools refused: Bash, Write."),
    (None, {"timed_out": True}, "longer than 10 minutes"),
    (None, {"cancelled": True}, "Cancelled."),
    ("", {"returncode": 1, "stderr": "error: unknown option '--permission-mode'"},
     "did not run (exit code 1): error: unknown option '--permission-mode'"),
])
def test_why_a_run_failed_is_said_in_words(result, kwargs, expected) -> None:
    out = outcome(result, **kwargs)
    reason = jobs.failure_reason(out, jobs.parse_result(out.stdout), 10)
    assert (reason is None) if expected is None else (expected in reason)


def test_the_result_is_the_last_json_line() -> None:
    assert jobs.parse_result('warning: slow\n{"a": 1}\n') == {"a": 1}
    assert jobs.parse_result("not json") == {}


# --- the queue ---------------------------------------------------------------------------------


def test_a_second_request_returns_the_job_already_queued(state: ServiceState) -> None:
    card = add_card(state)
    first, created = jobs.enqueue(state.engine, jobs.PREPARE, card)
    again, created_again = jobs.enqueue(state.engine, jobs.PREPARE, card)
    assert created and not created_again and again["id"] == first["id"]
    assert jobs.cancel(state.engine, first["id"])["status"] == "cancelled"
    assert jobs.enqueue(state.engine, jobs.PREPARE, card)[1] is True


def test_a_job_left_running_by_a_stopped_service_fails(state: ServiceState) -> None:
    job, _ = jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))
    jobs.claim_next(state.engine)
    assert jobs.reset_interrupted(state.engine) == 1
    assert "Spyglass stopped" in job_row(state, job["id"]).error


# --- Prepare detail ------------------------------------------------------------------------------


def test_prepare_detail_writes_the_note_in_todays_folder(state: ServiceState) -> None:
    card = add_card(state)
    job, _ = jobs.enqueue(state.engine, jobs.PREPARE, card)
    fake = FakeClaude(state, prepare_script)
    done = worker(state, fake).run_one()
    assert done["status"] == "ok", done
    assert done["message"] == "A note on optogenetics." and done["cost_usd"] == 0.21
    assert fake.cwd == state.settings.vault_path
    note = Path(card_note(state, card))
    assert note.parent.parent == state.settings.vault_path / "03 RESOURCES/Spyglass/Brief notes"
    assert note.name == "Optogenetics, explained.md"
    post = frontmatter.load(note)
    assert post["spyglass_item"] == card and post["source"] == "https://x.test/a"
    assert post.content.startswith("Bottom line.")
    assert done["note_path"].startswith("03 RESOURCES/Spyglass/Brief notes/")
    with Session(state.engine) as session:
        log = session.exec(select(RunLog)).one()
    assert log.source == "claude-job:prepare-detail" and log.status == "ok"


def test_a_run_that_never_reports_fails(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))
    done = worker(state, FakeClaude(state, result={**OK_RESULT, "result": "I wrote it."})).run_one()
    assert done["status"] == "failed"
    assert done["error"] == "Claude finished without reporting back to Spyglass: I wrote it."


def test_success_without_a_saved_note_fails(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))

    def script(st, job_id, _stop):
        call(st, "job_start", {"job_id": job_id})
        call(st, "job_finish", {"job_id": job_id, "ok": True, "message": "Done"})

    done = worker(state, FakeClaude(state, script)).run_one()
    assert done["status"] == "failed" and "never saved the note" in done["error"]


def test_a_reported_failure_shows_claudes_reason(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))

    def script(st, job_id, _stop):
        call(st, "job_finish", {"job_id": job_id, "ok": False, "message": "The page is paywalled."})

    done = worker(state, FakeClaude(state, script)).run_one()
    assert done["status"] == "failed" and done["error"] == "The page is paywalled."


def test_no_claude_or_no_vault_fails_before_running(state: ServiceState, monkeypatch) -> None:
    card = add_card(state)
    state.settings.claude_command = None
    monkeypatch.setattr(jobs, "find_claude", lambda settings: None)
    jobs.enqueue(state.engine, jobs.PREPARE, card)
    fake = FakeClaude(state)
    assert "Claude Code was not found" in worker(state, fake).run_one()["error"]
    state.settings.vault_path = None
    jobs.enqueue(state.engine, jobs.PREPARE, card)
    assert "vault folder" in worker(state, fake).run_one()["error"]
    assert fake.commands == []


def test_a_cancelled_run_is_stopped(state: ServiceState) -> None:
    job, _ = jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))

    def script(st, job_id, should_stop):
        jobs.cancel(st.engine, job_id)
        assert should_stop() is True

    done = worker(state, FakeClaude(state, script, cancelled=True)).run_one()
    assert done["status"] == "cancelled"


def test_job_tools_refuse_jobs_that_are_not_running(state: ServiceState) -> None:
    job, _ = jobs.enqueue(state.engine, jobs.FILE, add_card(state))
    assert call(state, "job_start", {"job_id": job["id"]})["error"] == "not_running"
    jobs.claim_next(state.engine)
    refused = call(state, "job_save_detail", {"job_id": job["id"], "title": "t", "markdown": "m"})
    assert refused["error"] == "wrong_kind"
    assert call(state, "job_start", {"job_id": 999})["error"] == "unknown_job"
    served = call(state, "get_instructions", {"job": "file-note"})
    assert "job_file_note" in served["instructions"]
    assert "vault_move" not in served["instructions"]


# --- File it -----------------------------------------------------------------------------------


def note_for(state: ServiceState, card: int) -> Path:
    return write_detail_note(state.settings, state.engine, card, "Optogenetics, explained",
                             "Body", today=date(2026, 10, 15))


def make_folder(state: ServiceState, folder: str) -> None:
    """A folder in the vault, as the user's projects and areas are."""
    (state.settings.vault_path / folder.strip("/")).mkdir(parents=True, exist_ok=True)


def file_script(folder: str):
    """A filing run that picks `folder` and asks Spyglass to move the note there."""
    def script(st, job_id, _stop):
        start = call(st, "job_start", {"job_id": job_id})
        assert "job_file_note" in start["instructions"] and "vault_move" not in start["instructions"]
        moved = call(st, "job_file_note", {"job_id": job_id, "folder": folder})
        if moved.get("moved"):
            call(st, "job_finish", {"job_id": job_id, "ok": True,
                                    "message": f"Filed to {folder.strip('/')}: about optogenetics."})
        else:
            call(st, "job_finish", {"job_id": job_id, "ok": False, "message": moved["detail"]})
    return script


def test_file_it_moves_the_note_and_says_where(state: ServiceState) -> None:
    card = add_card(state)
    note = note_for(state, card)
    make_folder(state, "02 AREAS/Imaging")
    jobs.enqueue(state.engine, jobs.FILE, card)
    done = worker(state, FakeClaude(state, file_script("02 AREAS/Imaging"))).run_one()
    assert done["status"] == "ok", done
    assert done["message"] == "Filed to 02 AREAS/Imaging: about optogenetics."
    assert done["note_path"] == "02 AREAS/Imaging/Optogenetics, explained.md"
    assert Path(card_note(state, card)).is_file()
    # Spyglass asked Obsidian to move exactly the job's own note, and nothing else.
    source = note.relative_to(state.settings.vault_path).as_posix()
    assert state.obsidian_move.calls == [(source, "02 AREAS/Imaging/")]


def test_file_it_believes_only_a_move_spyglass_made(state: ServiceState) -> None:
    """A run that says it filed the note, without asking Spyglass to move it, has not filed it."""
    card = add_card(state)
    note_for(state, card)
    jobs.enqueue(state.engine, jobs.FILE, card)

    def script(st, job_id, _stop):
        call(st, "job_finish", {"job_id": job_id, "ok": True, "message": "Filed"})

    done = worker(state, FakeClaude(state, script)).run_one()
    assert done["status"] == "failed" and "made no move" in done["error"]
    assert "Brief notes" in card_note(state, card)
    assert state.obsidian_move.calls == []


def test_file_it_fails_with_the_reason_when_obsidian_refuses(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    make_folder(state, "02 AREAS/Imaging")
    state.obsidian_move.error = "Destination already exists"
    jobs.enqueue(state.engine, jobs.FILE, card)
    done = worker(state, FakeClaude(state, file_script("02 AREAS/Imaging"))).run_one()
    assert done["status"] == "failed" and "Destination already exists" in done["error"]
    assert "Brief notes" in card_note(state, card)


def test_file_it_opens_obsidian_and_waits_for_it(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    make_folder(state, "02 AREAS/Imaging")
    jobs.enqueue(state.engine, jobs.FILE, card)
    answers = iter([False, False, True])
    opened: list[str] = []
    fake = FakeClaude(state, file_script("02 AREAS/Imaging"))
    done = worker(state, fake, probe=lambda url: next(answers), opened=opened).run_one()
    assert opened == ["obsidian://open?vault=Vault"]
    assert done["status"] == "ok"


def test_file_it_gives_up_when_obsidian_does_not_open(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    jobs.enqueue(state.engine, jobs.FILE, card)
    fake = FakeClaude(state)
    done = worker(state, fake, probe=lambda url: False, opened=[]).run_one()
    assert done["status"] == "failed" and "Obsidian did not answer" in done["error"]
    assert fake.commands == []


# --- detailed notes ----------------------------------------------------------------------------


def test_note_names_are_safe_and_a_second_preparation_reuses_the_file(state: ServiceState) -> None:
    assert note_filename('A/B: "C"? #1 [x]') == "A B C 1 x"
    assert note_filename("   ") == "Spyglass item"
    card = add_card(state)
    first = note_for(state, card)
    again = write_detail_note(state.settings, state.engine, card, "New title", "Body 2",
                              today=date(2026, 10, 16))
    assert again == first and frontmatter.load(first).content == "Body 2"
    other = add_card(state, "Optogenetics, explained ")
    assert note_for(state, other).name == f"Optogenetics, explained ({other}).md"


def test_delete_moves_an_unfiled_note_to_the_trash(state: ServiceState) -> None:
    card = add_card(state)
    note = note_for(state, card)
    assert delete_detail_note(state.settings, state.engine, card) == \
        ".trash/Optogenetics, explained.md"
    assert not note.exists() and card_note(state, card) is None
    with Session(state.engine) as session:
        assert session.get(Card, card).feedback == "down"
    with pytest.raises(NoteNotRemovable):
        delete_detail_note(state.settings, state.engine, card)


# --- running a real process ------------------------------------------------------------------


def test_a_real_process_is_run_timed_out_and_stopped(tmp_path: Path) -> None:
    py = sys.executable
    echo = [py, "-c", "import sys, json; print(json.dumps({'got': sys.stdin.read()}))"]
    done = jobs.run_claude(echo, tmp_path, 10, lambda: False, prompt="job 7", poll_s=0.1)
    assert done.returncode == 0 and jobs.parse_result(done.stdout) == {"got": "job 7"}
    slow = [py, "-c", "import time; time.sleep(30)"]
    assert jobs.run_claude(slow, tmp_path, 0.3, lambda: False, poll_s=0.1).timed_out is True
    assert jobs.run_claude(slow, tmp_path, 10, lambda: True, poll_s=0.1).cancelled is True


# --- the dashboard API ---------------------------------------------------------------------------


def make_client(tmp_path: Path, vault: bool = True) -> TestClient:
    folder = tmp_path / "Vault"
    folder.mkdir(exist_ok=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data",
                        vault_path=folder if vault else None)
    return TestClient(create_app(settings, link_opener=lambda url: None,
                                 skip_startup_embed=True))


def test_the_api_queues_jobs_and_reports_the_note(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        st = client.app.state.service_state
        card = add_card(st)
        body = {"kind": "file-note", "card_id": card}
        assert client.post("/api/jobs", json=body).status_code == 409  # no note yet
        assert client.post("/api/jobs", content=json.dumps(body)).status_code == 415
        first = client.post("/api/jobs", json={"kind": "prepare-detail", "card_id": card}).json()
        assert first["created"] is True and first["job"]["status"] == "queued"
        again = client.post("/api/jobs", json={"kind": "prepare-detail", "card_id": card}).json()
        assert again["created"] is False
        assert [j["id"] for j in client.get("/api/jobs/active").json()] == [first["job"]["id"]]
        listed = client.get(f"/api/cards/{card}/jobs").json()
        assert listed["note"] == {"path": None, "unfiled": False} and len(listed["jobs"]) == 1
        cancelled = client.post(f"/api/jobs/{first['job']['id']}/cancel", json={}).json()
        assert cancelled["status"] == "cancelled"
        note_for(st, card)
        listed = client.get(f"/api/cards/{card}/jobs").json()
        assert listed["note"]["unfiled"] is True
        assert listed["note"]["path"].endswith("Optogenetics, explained.md")
        assert client.post("/api/jobs", json={"kind": "prepare-detail",
                                              "card_id": card}).status_code == 409
        assert client.post("/api/jobs", json={"kind": "nope", "card_id": card}).status_code == 422
        assert client.post("/api/jobs", json={"kind": "file-note",
                                              "card_id": 999}).status_code == 404
        trashed = client.post(f"/api/cards/{card}/detail-note/delete", json={})
        assert trashed.json() == {"trashed": ".trash/Optogenetics, explained.md"}
        assert client.post(f"/api/cards/{card}/detail-note/delete", json={}).status_code == 409


def test_the_api_needs_a_vault(tmp_path: Path) -> None:
    with make_client(tmp_path, vault=False) as client:
        card = add_card(client.app.state.service_state)
        response = client.post("/api/jobs", json={"kind": "prepare-detail", "card_id": card})
        assert response.status_code == 409


def test_job_settings_can_be_edited(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        saved = client.patch("/api/settings", json={"claude_command": "C:/claude.exe",
                                                    "job_timeout_minutes": 5}).json()
        assert saved["claude_command"] == "C:/claude.exe" and saved["job_timeout_minutes"] == 5
        cleared = client.patch("/api/settings", json={"claude_command": ""}).json()
        assert cleared["claude_command"] is None
        assert client.patch("/api/settings", json={"job_timeout_minutes": 0}).status_code == 422


# --- review fixes ------------------------------------------------------------------------------


def test_a_double_click_queues_one_job(state: ServiceState) -> None:
    import threading

    card = add_card(state)
    results: list[bool] = []
    threads = [threading.Thread(target=lambda: results.append(
        jobs.enqueue(state.engine, jobs.PREPARE, card)[1])) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1


def test_a_job_that_no_longer_makes_sense_is_not_run(state: ServiceState) -> None:
    card = add_card(state)
    jobs.enqueue(state.engine, jobs.PREPARE, card)
    note_for(state, card)
    fake = FakeClaude(state)
    assert worker(state, fake).run_one()["error"] == "This item already has a note."
    other = add_card(state, "Another")
    jobs.enqueue(state.engine, jobs.FILE, other)
    assert "nothing to file" in worker(state, fake).run_one()["error"]
    assert fake.commands == []


def test_a_reported_success_stands_when_the_run_then_times_out(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))
    done = worker(state, FakeClaude(state, prepare_script, timed_out=True)).run_one()
    assert done["status"] == "ok" and done["error"] is None


def test_an_error_inside_spyglass_never_leaves_a_job_running(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    done = worker(state, broken).run_one()
    assert done["status"] == "failed" and "database is locked" in done["error"]


def test_cancel_while_waiting_for_obsidian(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    job, _ = jobs.enqueue(state.engine, jobs.FILE, card)

    def probe(url):
        jobs.cancel(state.engine, job["id"])
        return False

    done = worker(state, FakeClaude(state), probe=probe, opened=[]).run_one()
    assert done["status"] == "cancelled"


def test_filing_fails_clearly_without_the_obsidian_server(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    (state.settings.vault_path / ".mcp.json").unlink()
    jobs.enqueue(state.engine, jobs.FILE, card)
    done = worker(state, FakeClaude(state)).run_one()
    assert done["status"] == "failed" and "could not find your Obsidian MCP server" in done["error"]


def test_slashes_around_the_folder_are_accepted(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    make_folder(state, "02 AREAS/Imaging")
    jobs.enqueue(state.engine, jobs.FILE, card)
    script = file_script("/02 AREAS\\Imaging/")
    assert worker(state, FakeClaude(state, script)).run_one()["status"] == "ok"
    assert state.obsidian_move.calls[0][1] == "02 AREAS/Imaging/"


def test_a_note_moved_without_a_report_is_found_again(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    jobs.enqueue(state.engine, jobs.FILE, card)

    def moves_then_stops(st, job_id, _stop):
        old = Path(card_note(st, card))
        target = st.settings.vault_path / "02 AREAS"
        target.mkdir()
        os.replace(old, target / old.name)

    done = worker(state, FakeClaude(state, moves_then_stops, timed_out=True)).run_one()
    assert done["status"] == "failed"
    assert Path(card_note(state, card)).parts[-2:] == ("02 AREAS", "Optogenetics, explained.md")


def test_scripts_in_a_note_are_kept_as_text(state: ServiceState) -> None:
    card = add_card(state)
    path = write_detail_note(state.settings, state.engine, card, "T",
                             "x\n```dataviewjs\napp.vault.delete()\n```\nand `$= dv.pages()`")
    body = frontmatter.load(path).content
    assert "dataviewjs" not in body and "`$=" not in body


def test_reserved_and_taken_names(state: ServiceState) -> None:
    assert note_filename("CON") == "CON note"
    card = add_card(state)
    first = write_detail_note(state.settings, state.engine, card, "Same", "a",
                              today=date(2026, 10, 15))
    second_card, third_card = add_card(state, "b"), add_card(state, "c")
    second = write_detail_note(state.settings, state.engine, second_card, "Same", "b",
                               today=date(2026, 10, 15))
    (second.parent / f"Same ({third_card}).md").write_text("someone else's")
    third = write_detail_note(state.settings, state.engine, third_card, "Same", "c",
                              today=date(2026, 10, 15))
    assert len({first, second, third}) == 3
    assert (second.parent / f"Same ({third_card}).md").read_text() == "someone else's"


def test_deleting_a_note_that_is_already_gone(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card).unlink()
    assert delete_detail_note(state.settings, state.engine, card) is None
    with Session(state.engine) as session:
        assert session.get(Card, card).feedback is None
    assert card_note(state, card) is None


def test_the_linked_session_records_a_moved_note(state: ServiceState) -> None:
    card = add_card(state)
    note = note_for(state, card)
    target = state.settings.vault_path / "02 AREAS"
    target.mkdir()
    os.replace(note, target / note.name)
    done = call(state, "set_item_note", {"code": f"#{card}",
                                         "note_path": "02 AREAS/Optogenetics, explained"})
    assert done == {"recorded": True, "note_path": "02 AREAS/Optogenetics, explained.md"}
    refused = call(state, "set_item_note", {"code": card, "note_path": "../outside.md"})
    assert refused["error"] == "outside_vault"


def test_the_api_guards_filing_and_deleting(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        st = client.app.state.service_state
        card = add_card(st)
        note = note_for(st, card)
        queued = client.post("/api/jobs", json={"kind": "file-note", "card_id": card}).json()
        blocked = client.post(f"/api/cards/{card}/detail-note/delete", json={})
        assert blocked.status_code == 409
        client.post(f"/api/jobs/{queued['job']['id']}/cancel", json={})
        filed = st.settings.vault_path / "02 AREAS"
        filed.mkdir()
        os.replace(note, filed / note.name)
        with Session(st.engine) as session:
            row = session.get(Card, card)
            row.briefing_path = str(filed / note.name)
            session.add(row)
            session.commit()
        again = client.post("/api/jobs", json={"kind": "file-note", "card_id": card})
        assert again.status_code == 409 and "already filed" in again.json()["detail"]


@pytest.mark.parametrize("folder", ["/abs/notes", "C:/Notes", "..\\up", "a/../../b", "  "])
def test_the_notes_folder_must_be_inside_the_vault(tmp_path: Path, folder: str) -> None:
    with make_client(tmp_path) as client:
        assert client.patch("/api/settings",
                            json={"detail_notes_subdir": folder}).status_code == 422


def test_obsidian_settings_can_be_edited(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        saved = client.patch("/api/settings", json={
            "obsidian_mcp_server": "obsidian", "obsidian_probe_url": "https://127.0.0.1:27124/",
            "detail_notes_subdir": "Notes\\Spyglass/"}).json()
        assert saved["obsidian_probe_url"] == "https://127.0.0.1:27124/"
        assert saved["detail_notes_subdir"] == "Notes/Spyglass"
        assert client.patch("/api/settings",
                            json={"obsidian_probe_url": "http://example.com/"}).status_code == 422


# --- the user's PC test: filings landed in Spyglass's own folder --------------------------------


def test_filing_into_a_spyglass_folder_is_refused_before_anything_moves(state: ServiceState) -> None:
    card = add_card(state)
    note_for(state, card)
    make_folder(state, "03 RESOURCES/Spyglass")
    make_folder(state, "02 AREAS/Imaging")
    jobs.enqueue(state.engine, jobs.FILE, card)
    start = {}

    def script(st, job_id, stop):
        start.update(call(st, "job_start", {"job_id": job_id}))
        file_script("03 RESOURCES/Spyglass")(st, job_id, stop)

    done = worker(state, FakeClaude(state, script)).run_one()
    assert "03 RESOURCES/Spyglass/Brief notes" in start["instructions"]
    assert done["status"] == "failed" and "Spyglass's own folders" in done["error"]
    # Nothing moved, and File it is still offered.
    assert state.obsidian_move.calls == []
    assert "Brief notes" in card_note(state, card)
    jobs.enqueue(state.engine, jobs.FILE, card)
    again = worker(state, FakeClaude(state, file_script("02 AREAS/Imaging"))).run_one()
    assert again["status"] == "ok"


def test_an_old_briefing_in_a_spyglass_folder_can_be_filed_and_deleted(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        st = client.app.state.service_state
        card = add_card(st)
        old = st.settings.vault_path / st.settings.briefing_subdir / "20260701-old.md"
        old.parent.mkdir(parents=True)
        old.write_text("# Old briefing")
        with Session(st.engine) as session:
            row = session.get(Card, card)
            row.briefing_path = str(old)
            session.add(row)
            session.commit()
        assert client.get(f"/api/cards/{card}/jobs").json()["note"]["unfiled"] is True
        assert client.post("/api/jobs", json={"kind": "file-note", "card_id": card}).json()["created"]
        client.post(f"/api/jobs/{jobs.active_jobs(st.engine)[0]['id']}/cancel", json={})
        assert client.post(f"/api/cards/{card}/detail-note/delete", json={}).status_code == 200


# --- models and the user's Claude limits ------------------------------------------


def stream(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


def rate_event(status: str = "allowed", five: float = 0.5, week: float = 0.2,
               resets: float = 1792105800) -> dict:
    return {"type": "rate_limit_event", "rate_limit_info": {
        "status": status, "resetsAt": resets, "rateLimitType": "five_hour",
        "unifiedWindows": {"five_hour": {"utilization": five, "resetsAt": resets},
                           "seven_day": {"utilization": week, "resetsAt": resets + 86400}}}}


def test_each_job_names_its_model(state: ServiceState) -> None:
    config = Path("mcp.json")
    prepare = jobs.build_command(state.settings, "claude", jobs.PREPARE, config)
    filing = jobs.build_command(state.settings, "claude", jobs.FILE, config)
    assert prepare[prepare.index("--model") + 1] == "sonnet"
    assert filing[filing.index("--model") + 1] == "haiku"
    state.settings.job_model_file = "claude-sonnet-5-5"
    filing = jobs.build_command(state.settings, "claude", jobs.FILE, config)
    assert filing[filing.index("--model") + 1] == "claude-sonnet-5-5"


def test_a_job_records_its_model_and_the_usage_claude_reports(state: ServiceState) -> None:
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))

    class Streamed(FakeClaude):
        def __call__(self, command, cwd, timeout_s, should_stop, prompt):
            out = super().__call__(command, cwd, timeout_s, should_stop, prompt)
            result = {**OK_RESULT, "modelUsage": {"claude-sonnet-5-5": {"costUSD": 0.1}}}
            out.stdout = stream({"type": "system", "subtype": "init"}, rate_event(), result)
            return out

    done = worker(state, Streamed(state, prepare_script)).run_one()
    assert done["status"] == "ok" and done["model"] == "claude-sonnet-5-5"
    assert done["usage_five_hour"] == 0.5 and done["usage_week"] == 0.2


def test_a_limit_pauses_the_queue_until_the_reset(state: ServiceState) -> None:
    first, _ = jobs.enqueue(state.engine, jobs.PREPARE, add_card(state))
    jobs.enqueue(state.engine, jobs.PREPARE, add_card(state, "Second"))
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    reset = now + timedelta(hours=2)
    limited = stream(rate_event("rejected", five=1.0, resets=reset.timestamp()),
                     {**OK_RESULT, "is_error": True, "subtype": "success",
                      "result": "You've hit your session limit · resets 2pm"})

    class Limited(FakeClaude):
        def __call__(self, command, cwd, timeout_s, should_stop, prompt):
            out = super().__call__(command, cwd, timeout_s, should_stop, prompt)
            out.stdout = limited
            return out

    fake = Limited(state)
    w = worker(state, fake)
    w._now = lambda: now
    waiting = w.run_one()
    assert waiting["status"] == "queued" and waiting["id"] == first["id"]
    assert waiting["progress"].startswith("Waiting for Claude's usage limit to reset at")
    assert w.paused_until == reset
    assert w.run_one() is None and len(fake.commands) == 1  # nothing else starts
    w._now = lambda: reset + timedelta(minutes=1)
    w._run = FakeClaude(state, prepare_script)
    assert w.run_one()["status"] == "ok" and w.paused_until is None


def test_a_limit_message_without_a_reset_time_waits_half_an_hour() -> None:
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    out = jobs.RunOutcome(1, json.dumps({"is_error": True, "result": "You've hit your weekly limit"}), "")
    assert jobs.limit_reset(out, jobs.parse_result(out.stdout), now) == now + jobs.LIMIT_WAIT
    ok = jobs.RunOutcome(0, stream(rate_event(), OK_RESULT), "")
    assert jobs.limit_reset(ok, jobs.parse_result(ok.stdout), now) is None


def test_job_models_can_be_set(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        saved = client.patch("/api/settings", json={"job_model_prepare": "opus",
                                                    "job_model_file": "sonnet"}).json()
        assert saved["job_model_prepare"] == "opus" and saved["job_model_file"] == "sonnet"
        assert client.patch("/api/settings",
                            json={"job_model_file": "haiku; rm -rf"}).status_code == 422
        card = add_card(client.app.state.service_state)
        assert client.get(f"/api/cards/{card}/jobs").json()["paused_until"] is None
