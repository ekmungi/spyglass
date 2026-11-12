"""The background filing run: one hidden Claude Code session in the vault, never waiting for anyone.

`run_filing` decides what the run is for (`plan_work`), checks what it needs before spending
anything, then starts `claude -p` in the vault folder with the vault skills' plugin loaded, the
tools of `filing_access` and nothing else, and the short request of
`filing_request.build_run_request` on standard input (never an article's text). It waits at most
`RUN_TIMEOUT_S`, records the usage under the purpose "filing", and stores the outcome
(`filing_status`). One run at a time: an in-process lock plus a lock file in the data folder that
a crashed process cannot leave held (the same lock file the collection cycle uses, under another
name).

Flags (Claude Code 2.1.x): `-p --output-format stream-json --verbose`, `--model`,
`--restricted` (no settings files of the owner: no allow rules, other plugins or hooks of theirs;
file tools confined to the vault and the plugin folder), `--strict-mcp-config --mcp-config`
(only the two tool servers Spyglass names), `--settings` (the allow and deny lists),
`--plugin-dir` and `--add-dir` (the vault skills and their reference files), `--tools` (the
built-in tools of `filing_access.BUILT_IN`), `--permission-mode dontAsk` (anything not allowed is
refused without asking), `--max-turns` and `--no-session-persistence`.
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.filing_config import (
    BACKGROUND_UNAVAILABLE, SKILLS_NOT_CONFIGURED, background_unlocked, skills_configured,
)
from spyglass_service.claude_jobs import (
    ObsidianServerMissing, child_env, find_claude, find_obsidian_server,
)
from spyglass_service.radar import filing_access as access
from spyglass_service.radar import filing_status as status
from spyglass_service.radar.assist.engines.process import ChildProcess
from spyglass_service.radar.assist.engines.safe_args import assert_cmd_safe, valid_model
from spyglass_service.radar.cycle_lock import CycleFileLock
from spyglass_service.radar.filing_outcome import parse_stream, stop_reason
from spyglass_service.radar.filing_plan import approved_rows, unplanned_ids
from spyglass_service.radar.filing_questions import answered_unapplied
from spyglass_service.radar.filing_queue import queued_ids, waiting
from spyglass_service.radar.filing_request import build_run_request
from spyglass_service.radar.filing_tables import FilingProposal, FilingQuestion
from spyglass_service.radar.models import utcnow
from spyglass_service.skill_sync import default_repo_skills_dir

logger = logging.getLogger(__name__)

RUN_TIMEOUT_S = 45 * 60.0
MAX_ITEMS = {"plan": 40, "file": 10}
MAX_TURNS = {"plan": 80, "file": 200}
LOCK_FILE = "filing-run.lock"
_run_lock = threading.Lock()


@dataclass(frozen=True)
class LaunchResult:
    """What the child process left: its output lines, the tail of its errors and how it ended."""

    lines: list[str]
    stderr: str
    returncode: int | None
    timed_out: bool
    seconds: float


# (command, working folder, environment, standard input, timeout seconds) -> LaunchResult.
Launch = Callable[[list[str], Path, dict[str, str], str, float], LaunchResult]
Probe = Callable[[str], bool]
# settings -> the owner's Obsidian server entry; raises ObsidianServerMissing. Tests inject one.
FindServer = Callable[[object], dict]


def _obsidian_entry(settings, vault: Path | None, find_server: FindServer) -> dict | None:
    """The owner's Obsidian server entry as seen from `vault`, or None when it is configured nowhere."""
    try:
        return find_server(settings.model_copy(update={"vault_path": vault}))
    except ObsidianServerMissing:
        return None


@dataclass(frozen=True)
class RunWork:
    """What one run is for: its kind, its items and how many answers it applies."""

    kind: str
    item_ids: list[int]
    answers: int


def default_launch(command: list[str], cwd: Path, env: dict[str, str], stdin_text: str,
                   timeout_s: float) -> LaunchResult:
    """Run the session with no window; stop the whole process tree at the time limit."""
    started = time.monotonic()
    child = ChildProcess(command, cwd=cwd, env=env, stdin_text=stdin_text)
    lines: list[str] = []
    timed_out = False
    try:
        for line in child.lines(timeout_s=timeout_s):
            if line is not None:
                lines.append(line)
    except TimeoutError:
        timed_out = True
    finally:
        child.close()
    return LaunchResult(lines, child.stderr_tail, child.returncode, timed_out,
                        time.monotonic() - started)


def plan_work(engine: Engine, mode: str) -> RunWork | None:
    """What a run in `mode` should do now, or None when there is nothing to do.

    auto: file the oldest queued items and apply answers. plan_first: file the approved rows
    first; else propose for the items without a row; else only apply answers.
    """
    answers = len([a for a in answered_unapplied(engine) if a["note_path"]])
    if mode == "auto":
        items = [e.item_id for e in waiting(engine)][:MAX_ITEMS["file"]]
        return RunWork("file", items, answers) if items or answers else None
    if mode == "plan_first":
        approved = [r["item_id"] for r in approved_rows(engine)][:MAX_ITEMS["file"]]
        if approved:
            return RunWork("file", approved, answers)
        unplanned = unplanned_ids(engine)[:MAX_ITEMS["plan"]]
        if unplanned:
            return RunWork("plan", unplanned, 0)
        return RunWork("file", [], answers) if answers else None
    return None


def build_command(claude: str, *, model: str, kind: str, mcp_file: Path, permissions: Path,
                  plugin_root: Path, own_plugin: Path) -> list[str]:
    """The argument list for one session; raises ValueError for an unsafe model or argument.

    `plugin_root` holds the vault skills (its folder is also readable, for their reference
    files); `own_plugin` carries Spyglass's own filing skill.
    """
    if not valid_model(model):
        raise ValueError("The filing model name is not valid.")
    command = [
        claude, "-p", "--output-format", "stream-json", "--verbose", "--model", model,
        "--restricted", "--strict-mcp-config", "--mcp-config", str(mcp_file),
        "--settings", str(permissions), "--plugin-dir", str(plugin_root),
        "--plugin-dir", str(own_plugin),
        "--add-dir", str(plugin_root), "--tools", ",".join(access.BUILT_IN),
        "--permission-mode", "dontAsk", "--max-turns", str(MAX_TURNS[kind]),
        "--no-session-persistence",
    ]
    assert_cmd_safe(command)
    return command


def _counts(engine: Engine, run: dict) -> dict:
    """Items filed, questions open and rows pending for the run's items, and items left.

    A run's items had no plan row and no open question when it began (a plan run takes only
    unplanned items; a filing run takes queued ones, which are asked about only once filed), so
    what exists for them now is this run's work.
    """
    item_ids = run.get("item_ids") or []
    with Session(engine) as session:
        still = queued_ids(session, item_ids)
        asked = session.exec(select(FilingQuestion.item_id).where(
            FilingQuestion.item_id.in_(item_ids), FilingQuestion.answer.is_(None))).all()
        proposed = set(session.exec(select(FilingProposal.item_id).where(
            FilingProposal.item_id.in_(item_ids), FilingProposal.decision == "pending")).all())
    left = [i for i in item_ids if i in still and (run["kind"] == "file" or i not in proposed)]
    filed = len(item_ids) - len(still) if run["kind"] == "file" else 0
    return {"filed": filed, "asked": len(set(asked)), "proposed": len(proposed), "left": left}


class _Prepared:
    """Everything checked before a session starts; `problem` names the first missing thing."""

    def __init__(self, settings, kind: str, vault: Path | None, plugins_json: Path,
                 local_app_data: str | None, probe: Probe, find_server: FindServer) -> None:
        """Look up the vault, the command, the plugin, the launcher and the Obsidian server."""
        self.problem: str | None = None
        self.detail = ""
        self.vault, self.claude = vault, find_claude(settings)
        name = str(getattr(settings, "radar_filing_plugin", "") or "")
        self.plugin_name = name
        self.plugin = access.find_plugin(name, plugins_json) if name else None
        self.launchers = (access.vault_launchers(self.plugin, name, local_app_data)
                          if self.plugin else [])
        self.obsidian_name = settings.obsidian_mcp_server
        self.obsidian = _obsidian_entry(settings, vault, find_server)
        if vault is None or not vault.is_dir():
            self.problem = "no_vault"
        elif not name or not skills_configured(settings):
            self.problem, self.detail = "skills_missing", SKILLS_NOT_CONFIGURED
        elif self.claude is None:
            self.problem = "claude_missing"
        elif self.plugin is None:
            self.problem = "skills_missing"
        elif kind == "file" and self.obsidian is None:
            self.problem = "tools_missing"
        elif kind == "file" and not probe(str(self.obsidian.get("url") or "")):
            self.problem = "obsidian_unreachable"


def _record_usage(engine: Engine, facts, model: str, seconds: float) -> None:
    """Store the run's tokens and cost under the purpose "filing" (never raises)."""
    from spyglass_service.radar import usage
    from spyglass_service.radar.usage_parse import claude_tokens

    used = list((facts.result.get("modelUsage") or {}).keys())
    usage.record_call(engine, purpose="filing", provider="claude_code",
                      model=used[0] if used else model, tokens=claude_tokens(facts.result),
                      duration_ms=int(seconds * 1000))


@dataclass(frozen=True)
class RunOptions:
    """Overrides for one run; None means "from the settings" (or the real launcher and lookups).

    A trial passes `mode`, `vault`, `port` and `model` without changing any saved setting; tests
    pass `launch`, `probe`, `find_server`, `plugins_json` and `local_app_data`.
    """

    mode: str | None = None
    vault: Path | None = None
    port: int | None = None
    model: str | None = None
    launch: Launch | None = None
    probe: Probe | None = None
    find_server: FindServer | None = None
    plugins_json: Path | None = None
    local_app_data: str | None = None
    skills_dir: Path | None = None


def run_filing(engine: Engine, settings, options: RunOptions = RunOptions(),
               now: Callable[[], datetime] = utcnow) -> dict:
    """Start one background run if none is running; returns the finished status or a short result.

    Returns {"result": "off"} when the mode is off, {"result": "busy"} when a run holds the lock,
    {"result": "nothing"} when there is no work, and otherwise the stored status of the run. While
    background filing is locked in this version (no developer unlock in the environment) nothing
    starts, whatever the mode: the result is a refusal with the reason "failed" and a plain detail.
    """
    mode = options.mode or settings.radar_filing_mode
    if mode not in status.MODES[1:]:
        return {"result": "off"}
    if not background_unlocked():
        return {"result": "stopped", "reason": "failed", "detail": BACKGROUND_UNAVAILABLE}
    if not _run_lock.acquire(blocking=False):
        return {"result": "busy"}
    try:
        lock = CycleFileLock(Path(settings.data_dir) / LOCK_FILE)
        if not lock.acquire():
            return {"result": "busy"}
        try:
            status.recover_crashed(engine, now=now())
            return _run_locked(engine, settings, mode, options, now)
        finally:
            lock.release()
    finally:
        _run_lock.release()


def _prepare(settings, kind: str, options: RunOptions, vault: Path | None) -> "_Prepared":
    """The checks before a session, with the real lookups unless the options replace them."""
    from spyglass_service.job_worker import obsidian_running

    plugins_json = options.plugins_json or (
        Path.home() / ".claude" / "plugins" / "installed_plugins.json")
    local = (options.local_app_data if options.local_app_data is not None
             else os.environ.get("LOCALAPPDATA"))
    return _Prepared(settings, kind, vault, plugins_json, local,
                     options.probe or obsidian_running, options.find_server or find_obsidian_server)


def _run_locked(engine: Engine, settings, mode: str, options: RunOptions,
                now: Callable[[], datetime]) -> dict:
    """The body of `run_filing`, under the lock."""
    work = plan_work(engine, mode)
    if work is None:
        return {"result": "nothing"}
    vault = options.vault or settings.vault_path
    model = options.model or settings.radar_filing_model
    ready = _prepare(settings, work.kind, options, Path(vault) if vault else None)
    run = status.begin_run(engine, mode=mode, kind=work.kind, model=model,
                           item_ids=work.item_ids, now=now())
    if ready.problem:
        logger.info("filing run not started: %s", ready.problem)
        return status.finish_run(engine, run["run_id"], result="stopped", reason=ready.problem,
                                 detail=ready.detail, now=now())
    folder = Path(settings.data_dir) / "filing"
    config, extra_env = access.mcp_config(options.port or settings.port, ready.obsidian,
                                          ready.obsidian_name)
    obsidian = ready.obsidian_name if ready.obsidian else None
    try:
        command = build_command(
            ready.claude, model=model, kind=work.kind,
            mcp_file=access.write_mcp_config(folder, config),
            permissions=access.write_permissions(
                folder, access.allowed_tools(work.kind, obsidian=obsidian,
                                             launchers=ready.launchers),
                access.denied_tools(work.kind, obsidian=obsidian)),
            plugin_root=ready.plugin,
            own_plugin=access.session_plugin(folder, options.skills_dir or default_repo_skills_dir()))
    except (ValueError, OSError) as exc:
        return status.finish_run(engine, run["run_id"], result="stopped", reason="failed",
                                 detail=str(exc), now=now())
    request = build_run_request(run_id=run["run_id"], kind=work.kind, mode=mode,
                                items=len(work.item_ids), answers=work.answers,
                                launcher=ready.launchers[0] if ready.launchers else None,
                                server=access.SERVER)
    env = {**child_env(), **extra_env, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    try:
        outcome = (options.launch or default_launch)(command, Path(vault), env, request,
                                                     RUN_TIMEOUT_S)
    except OSError as exc:
        logger.warning("the filing session could not start", exc_info=True)
        return status.finish_run(engine, run["run_id"], result="stopped",
                                 reason="claude_missing", detail=str(exc), now=now())
    return _finish(engine, run, work, outcome, plugin=ready.plugin_name, obsidian=obsidian,
                   model=model, now=now)


def _finish(engine: Engine, run: dict, work: RunWork, outcome: LaunchResult, *, plugin: str,
            obsidian: str | None, model: str, now: Callable[[], datetime]) -> dict:
    """Read the session's output, record usage and store the outcome."""
    facts = parse_stream(outcome.lines)
    _record_usage(engine, facts, model, outcome.seconds)
    report = status.read_status(engine).get("report")
    code, detail, retry = stop_reason(
        facts, kind=work.kind, plugin=plugin, obsidian=obsidian, timed_out=outcome.timed_out,
        returncode=outcome.returncode, stdout="".join(outcome.lines), stderr=outcome.stderr,
        report=report, now=now())
    counts = _counts(engine, run)
    result = "stopped" if code else ("partial" if counts["left"] else "ok")
    if facts.denials:
        logger.info("filing run refused %d tool calls", len(facts.denials))
    cost = facts.result.get("total_cost_usd")
    return status.finish_run(
        engine, run["run_id"], result=result, reason=code, detail=detail,
        filed=counts["filed"], asked=counts["asked"], proposed=counts["proposed"],
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        duration_ms=int(outcome.seconds * 1000), retry_at=retry, refused=list(facts.denials),
        now=now())
