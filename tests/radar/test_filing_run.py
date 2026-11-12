"""Tests for the background filing runner (radar/filing_run.py) with a fake Claude process.

No test starts a real `claude`, touches the network or a real vault: the launcher, the Obsidian
probe and the Obsidian server lookup are replaced, and every path lives under tmp_path.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, select

from spyglass_service.claude_jobs import ObsidianServerMissing
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_plan, filing_queue, filing_status
from spyglass_service.radar.filed import record_filed
from spyglass_service.radar.filing_run import LOCK_FILE, LaunchResult, RunOptions, run_filing
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.usage import UsageCall

NOW = datetime(2026, 11, 12, 21, 0, tzinfo=UTC)
SECRET = "Bearer not-a-real-key"
HEADLINE = "A headline that must never reach the command line"


def init_line(plugins=("vault-tool",), spyglass="connected", obsidian="connected") -> str:
    """The session's first line."""
    return json.dumps({"type": "system", "subtype": "init", "tools": ["Read"],
                       "mcp_servers": [{"name": "spyglass_filing", "status": spyglass},
                                       {"name": "obsidian-vault", "status": obsidian}],
                       "plugins": [{"name": p} for p in plugins],
                       "skills": ["vault-tool:ingest"]}) + "\n"


def result_line(**fields) -> str:
    """The session's last line."""
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "total_cost_usd": 0.42, "modelUsage": {"claude-sonnet-x": {}},
                       "usage": {"input_tokens": 100, "output_tokens": 50,
                                 "cache_read_input_tokens": 900}, **fields}) + "\n"


class FakeLaunch:
    """Records the call and plays a session: `act` runs as the session would, then the lines."""

    def __init__(self, lines=None, act=None, timed_out=False, returncode=0, stderr=""):
        """Keep the canned output and the action."""
        self.lines = lines if lines is not None else [init_line(), result_line()]
        self.act, self.timed_out, self.returncode, self.stderr = act, timed_out, returncode, stderr
        self.calls: list[dict] = []

    def __call__(self, command, cwd, env, stdin_text, timeout_s) -> LaunchResult:
        """Record and play."""
        self.calls.append({"command": command, "cwd": cwd, "env": env, "stdin": stdin_text})
        if self.act:
            self.act(stdin_text)
        return LaunchResult(list(self.lines), self.stderr, self.returncode, self.timed_out, 12.5)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A database with two queued items, a fake vault, plugin, launcher and settings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-child")
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED", "1")
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL", "vault-tool")
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL_COMMANDS", "lookup folder, lookup template")
    vault = tmp_path / "vault"
    (vault / "01 PROJECTS" / "Beta").mkdir(parents=True)
    (vault / "03 RESOURCES").mkdir(parents=True)
    plugin = tmp_path / "plugins" / "vault-tool"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "vault-tool.sh").write_text("#!/bin/sh", encoding="utf-8")
    listing = tmp_path / "installed_plugins.json"
    listing.write_text(json.dumps({"plugins": {"vault-tool@m": [{"installPath": str(plugin)}]}}),
                       encoding="utf-8")
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        for n in (1, 2):
            item = Item(source="rss", external_id=f"e{n}", title=HEADLINE, url=f"https://x.example/{n}")
            session.add(item)
            session.commit()
            session.add(Assessment(item_id=item.id, headline=HEADLINE, tier="top"))
            session.commit()
    for item_id in (1, 2):
        filing_queue.enqueue(engine, item_id)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault,
                        claude_command=str(tmp_path / "claude.exe"), radar_filing_mode="auto",
                        radar_filing_plugin="vault-tool", radar_filing_ingest_skill="vault-skills:ingest", radar_filing_manage_skill="vault-skills:manage")
    yield engine, settings, vault, listing, tmp_path
    engine.dispose()


def options(listing: Path, launch=None, *, probe=True, server=True, **changes) -> RunOptions:
    """Run options with every outside lookup replaced."""
    def find_server(_settings):
        if not server:
            raise ObsidianServerMissing("none")
        return {"type": "http", "url": "http://127.0.0.1:1/mcp/", "headers": {"Authorization": SECRET}}

    return RunOptions(launch=launch, probe=lambda _url: probe, find_server=find_server,
                      plugins_json=listing, local_app_data="", **changes)


def write_note(vault: Path, name: str) -> str:
    """Create a note file and return its vault-relative path."""
    (vault / "03 RESOURCES" / name).write_text("x", encoding="utf-8")
    return f"03 RESOURCES/{name}"


def test_a_successful_run_files_records_usage_and_clears_the_queue(env):
    engine, settings, vault, listing, _tmp = env

    def act(_stdin):
        for item_id in (1, 2):
            record_filed(engine, settings, item_id, write_note(vault, f"N{item_id}.md"))

    launch = FakeLaunch(act=act)
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert (status["result"], status["filed"], status["failures"]) == ("ok", 2, 0)
    assert status["cost_usd"] == 0.42 and status["next_retry"] is None
    assert filing_queue.count(engine) == 0
    with Session(engine) as session:
        [usage] = session.exec(select(UsageCall)).all()
    assert usage.provider == "claude_code" and usage.model == "claude-sonnet-x"
    # A background filing run is recorded under its own purpose, not lumped into "other".
    assert usage.purpose == "filing"
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (100, 50, 900)


def test_the_session_starts_restricted_in_the_vault_with_no_secret_on_disk(env):
    engine, settings, vault, listing, tmp = env
    launch = FakeLaunch()
    run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    [call] = launch.calls
    command = call["command"]
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in command
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep,Skill,ToolSearch,Bash"
    assert Path(command[command.index("--plugin-dir") + 1]) == tmp / "plugins" / "vault-tool"
    assert call["cwd"] == vault
    assert "ANTHROPIC_API_KEY" not in call["env"] and SECRET in call["env"].values()
    for flag in ("--mcp-config", "--settings"):
        assert SECRET not in Path(command[command.index(flag) + 1]).read_text(encoding="utf-8")
    allowed = json.loads(Path(command[command.index("--settings") + 1]).read_text())["permissions"]
    assert "mcp__obsidian-vault__vault_write" in allowed["allow"]
    assert "mcp__obsidian-vault__vault_delete" in allowed["deny"]


def test_the_request_names_the_run_and_never_carries_item_text(env):
    engine, settings, _vault, listing, _tmp = env
    launch = FakeLaunch()
    run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    stdin = launch.calls[0]["stdin"]
    assert HEADLINE not in stdin and "x.example" not in stdin
    run_id = filing_status.read_status(engine)["run_id"]
    assert run_id in stdin and "Background run" in stdin and "Items in this run: 2" in stdin
    assert 'bash "' in stdin  # the exact vault-tool prefix the run may use


def test_a_run_that_leaves_items_is_partial_and_waits(env):
    engine, settings, vault, listing, _tmp = env
    launch = FakeLaunch(act=lambda _s: record_filed(engine, settings, 1, write_note(vault, "A.md")))
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert (status["result"], status["filed"], status["failures"]) == ("partial", 1, 1)
    assert datetime.fromisoformat(status["next_retry"]) == NOW + timedelta(minutes=30)


@pytest.mark.parametrize("changes, reason", [
    ({"probe": False}, "obsidian_unreachable"),
    ({"server": False}, "tools_missing"),
])
def test_missing_obsidian_stops_a_filing_run_before_it_starts(env, changes, reason):
    engine, settings, _vault, listing, _tmp = env
    launch = FakeLaunch()
    status = run_filing(engine, settings, options(listing, launch, **changes), now=lambda: NOW)
    assert (status["result"], status["reason"]) == ("stopped", reason)
    assert launch.calls == [] and filing_queue.count(engine) == 2


def test_a_missing_plugin_or_vault_stops_before_anything_starts(env, tmp_path):
    engine, settings, _vault, _listing, _tmp = env
    launch = FakeLaunch()
    status = run_filing(engine, settings, options(tmp_path / "none.json", launch),
                        now=lambda: NOW)
    assert status["reason"] == "skills_missing" and launch.calls == []
    no_vault = settings.model_copy(update={"vault_path": tmp_path / "absent"})
    status = run_filing(engine, no_vault, options(_listing, launch), now=lambda: NOW)
    assert status["reason"] == "no_vault" and launch.calls == []


@pytest.mark.parametrize("launch, reason", [
    (FakeLaunch(lines=[init_line()], timed_out=True), "time_limit"),
    (FakeLaunch(lines=[init_line(plugins=())] + [result_line()]), "skills_missing"),
    (FakeLaunch(lines=[init_line(spyglass="failed"), result_line()]), "tools_missing"),
    (FakeLaunch(lines=[init_line(obsidian="failed"), result_line()]), "obsidian_unreachable"),
    (FakeLaunch(lines=[init_line(), result_line(is_error=True, result="Please run /login")]),
     "not_signed_in"),
    (FakeLaunch(lines=[], returncode=1, stderr="crashed on start"), "failed"),
])
def test_each_stop_reason_is_stored(env, launch, reason):
    engine, settings, _vault, listing, _tmp = env
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert (status["result"], status["reason"]) == ("stopped", reason)


def test_a_usage_limit_waits_for_its_reset(env):
    engine, settings, _vault, listing, _tmp = env
    reset = NOW + timedelta(hours=4)
    event = json.dumps({"type": "rate_limit_event",
                        "rate_limit_info": {"status": "rejected", "resetsAt": reset.timestamp()}})
    launch = FakeLaunch(lines=[init_line(), event + "\n", result_line(is_error=True, result="x")])
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert status["reason"] == "usage_limit" and status["next_retry"] == reset.isoformat()


def test_refused_tool_calls_are_kept(env):
    engine, settings, _vault, listing, _tmp = env
    denied = [{"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}]
    launch = FakeLaunch(lines=[init_line(), result_line(permission_denials=denied)])
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert status["refused"] == ["Bash: rm -rf /"]


def test_a_stale_lock_left_by_a_crash_does_not_block_and_the_old_run_is_closed(env):
    engine, settings, _vault, listing, _tmp = env
    filing_status.begin_run(engine, mode="auto", kind="file", model="sonnet", item_ids=[],
                            now=NOW - timedelta(hours=1))
    lock = Path(settings.data_dir) / LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 999_999_9, "started_at": (NOW - timedelta(hours=1))
                                .isoformat()}), encoding="utf-8")
    seen = {}
    launch = FakeLaunch(act=lambda _s: seen.update(filing_status.read_status(engine)))
    status = run_filing(engine, settings, options(listing, launch), now=lambda: NOW)
    assert launch.calls and seen["state"] == "running" and status["state"] == "idle"
    assert not lock.exists()


def test_a_live_lock_means_busy(env):
    engine, settings, _vault, listing, _tmp = env
    lock = Path(settings.data_dir) / LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getppid(), "started_at": datetime.now(UTC).isoformat()}),
                    encoding="utf-8")
    launch = FakeLaunch()
    assert run_filing(engine, settings, options(listing, launch), now=lambda: NOW) == {
        "result": "busy"}
    assert launch.calls == []


def test_off_and_nothing_to_do_start_nothing(env):
    engine, settings, _vault, listing, _tmp = env
    launch = FakeLaunch()
    off = settings.model_copy(update={"radar_filing_mode": "off"})
    assert run_filing(engine, off, options(listing, launch)) == {"result": "off"}
    for item_id in (1, 2):
        filing_queue.dequeue(engine, item_id)
    assert run_filing(engine, settings, options(listing, launch)) == {"result": "nothing"}
    assert launch.calls == []


def test_a_plan_first_run_plans_without_any_write_tool_and_files_approved_rows_next(env):
    engine, settings, _vault, listing, _tmp = env

    def plan(stdin):
        run = filing_status.read_status(engine)
        assert "Plan-first run" in stdin and "writes nothing" in stdin
        for item_id in run["item_ids"]:
            filing_plan.propose(engine, settings, item_id, becomes="resource note",
                                place="03 RESOURCES", name=f"N{item_id}")

    launch = FakeLaunch(act=plan)
    status = run_filing(engine, settings, options(listing, launch, mode="plan_first"),
                        now=lambda: NOW)
    assert (status["kind"], status["result"], status["proposed"]) == ("plan", "ok", 2)
    command = launch.calls[0]["command"]
    rules = json.loads(Path(command[command.index("--settings") + 1]).read_text())["permissions"]
    assert not [r for r in rules["allow"] if r.endswith(("vault_write", "vault_patch",
                                                          "radar_mark_filed"))]
    rows = filing_plan.plan_rows(engine)
    filing_plan.decide(engine, approved=[rows[0]["id"]], struck=[rows[1]["id"]])
    launch = FakeLaunch()
    status = run_filing(engine, settings, options(listing, launch, mode="plan_first"),
                        now=lambda: NOW)
    assert status["kind"] == "file" and status["item_ids"] == [1]
