"""Background jobs: hidden Claude runs that Spyglass starts for one item.

A job is queued from the dashboard and run by one worker thread, one at a time. Each run is
`claude -p` in the vault folder. Its tools come from a fixed allowed list, and anything else is
refused without asking (`--permission-mode dontAsk`), so a run never waits for a click. The run
calls `job_start` for its instructions (mcp_jobs.py) and reports with `job_finish`. Its JSON
result gives what it cost. A run fails, with the reason shown on the item, when:
- it errors;
- it runs out of time;
- it ends without reporting.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.models import ClaudeJob, RunLog

logger = logging.getLogger(__name__)

PREPARE = "prepare-detail"
FILE = "file-note"
KINDS = (PREPARE, FILE)
ACTIVE = ("queued", "running")

# Generous for a note: start, read the text, look for related notes, save, finish.
MAX_TURNS = 40
# Long enough to read the item's own words in the reason; an item shows one line.
REASON_MAX = 400
# The setting that names each job's model.
MODEL_SETTING = {PREPARE: "job_model_prepare", FILE: "job_model_file"}
# How long the queue waits after a limit message that came without a reset time.
LIMIT_WAIT = timedelta(minutes=30)
_LIMIT_TEXT = re.compile(r"hit your .{0,40}limit", re.IGNORECASE)

# What a run may do. Allowed: Spyglass's own tools only. A filing run names a
# folder to job_file_note, and Spyglass itself has Obsidian move the job's note: the run
# holds no Obsidian tool, so an article's text cannot steer it into moving other notes.
# Reading, globbing and searching inside the vault (the run's folder) need no rule, and reading
# outside it is refused, so no file tool is listed: a bare "Read" would allow any path.
# Denied outright, whatever the user's own settings allow: shell, file writes, web, subagents,
# and the Obsidian server's moving and writing tools (it is not loaded into a run at all; the
# names stay denied in case it ever is). An article's text must not be able to steer a run into
# sending vault content to a web address or changing notes.
SPYGLASS_TOOLS = {
    PREPARE: ("job_start", "job_save_detail", "job_finish", "get_item", "get_fulltext",
              "store_fulltext", "get_interest_profile", "get_preferences", "find_similar"),
    FILE: ("job_start", "job_file_note", "job_finish", "get_item"),
}
DENIED_TOOLS = ("Bash", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch",
                "WebSearch", "Task", "Agent")
# The only built-in tools a run is given (`--tools`); Spyglass's MCP tools are not built-in, so
# they still load. "Don't ask" refuses only tools that would need a permission prompt, and some
# built-in tools need none (scheduling, remote triggers, messages to other Claude sessions), so a
# deny list alone would have to keep up with every tool a Claude Code update adds.
BUILT_IN_TOOLS = ("Read", "Glob", "Grep")
OBSIDIAN_DENIED = ("vault_move", "vault_write", "vault_patch", "vault_delete")

# Environment variables a hidden run must not inherit. With an API key set, `claude -p` bills
# that key instead of the signed-in plan, without saying so. CLAUDECODE marks a Claude Code
# session; the service may have been started from one.
DROPPED_ENV = ("ANTHROPIC_API_KEY", "CLAUDECODE")

# Queueing, cancelling and claiming read then write a job row; one lock keeps a double click
# from queueing twice and a cancel from crossing the worker's claim.
_queue_lock = threading.Lock()


class ObsidianServerMissing(Exception):
    """The Obsidian MCP server a filing run needs is not configured anywhere Spyglass looks."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def find_claude(settings: Settings) -> str | None:
    """The Claude Code command: the setting, then PATH, then the native installer's folder."""
    if settings.claude_command:
        # A bare name ("claude") is looked up like a shell would, so claude.cmd is found too.
        return shutil.which(settings.claude_command) or settings.claude_command
    found = shutil.which("claude")
    if found:
        return found
    exe = "claude.exe" if sys.platform == "win32" else "claude"
    candidate = Path.home() / ".local" / "bin" / exe
    return str(candidate) if candidate.is_file() else None


def job_dict(job: ClaudeJob) -> dict:
    """A job as the dashboard and the MCP tools see it."""
    return {
        "id": job.id,
        "kind": job.kind,
        "card_id": job.card_id,
        "status": job.status,
        "note_path": job.note_path,
        "message": job.message,
        "progress": job.progress,
        "error": job.error,
        "cost_usd": job.cost_usd,
        "duration_ms": job.duration_ms,
        "num_turns": job.num_turns,
        "model": job.model,
        "usage_five_hour": job.usage_five_hour,
        "usage_week": job.usage_week,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def enqueue(engine: Engine, kind: str, card_id: int) -> tuple[dict, bool]:
    """Queue a job for a card, or return the one already queued or running: (job, created)."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    with _queue_lock, Session(engine) as session:
        existing = session.exec(
            select(ClaudeJob).where(ClaudeJob.card_id == card_id, ClaudeJob.kind == kind,
                                    ClaudeJob.status.in_(ACTIVE))  # type: ignore[attr-defined]
        ).first()
        if existing is not None:
            return job_dict(existing), False
        job = ClaudeJob(kind=kind, card_id=card_id)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job_dict(job), True


def jobs_for_card(engine: Engine, card_id: int, limit: int = 5) -> list[dict]:
    """A card's latest jobs, newest first."""
    with Session(engine) as session:
        rows = session.exec(
            select(ClaudeJob).where(ClaudeJob.card_id == card_id)
            .order_by(ClaudeJob.id.desc()).limit(limit)  # type: ignore[union-attr]
        ).all()
        return [job_dict(job) for job in rows]


def active_jobs(engine: Engine) -> list[dict]:
    """Every queued or running job, oldest first."""
    with Session(engine) as session:
        rows = session.exec(
            select(ClaudeJob).where(ClaudeJob.status.in_(ACTIVE))  # type: ignore[attr-defined]
            .order_by(ClaudeJob.id)  # type: ignore[arg-type]
        ).all()
        return [job_dict(job) for job in rows]


def get_job(engine: Engine, job_id: int) -> ClaudeJob | None:
    with Session(engine) as session:
        return session.get(ClaudeJob, job_id)


def cancel(engine: Engine, job_id: int) -> dict | None:
    """Cancel a job. A queued one ends now; a running one is stopped by the worker. None when
    there is no such job; a finished job is returned unchanged."""
    with _queue_lock, Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        if job is None:
            return None
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = utcnow()
        elif job.status == "running":
            job.cancel_requested = True
        session.add(job)
        session.commit()
        session.refresh(job)
        return job_dict(job)


def reset_interrupted(engine: Engine) -> int:
    """Fail the jobs a previous service left running: their Claude run is gone."""
    with Session(engine) as session:
        stuck = session.exec(select(ClaudeJob).where(ClaudeJob.status == "running")).all()
        for job in stuck:
            job.status = "failed"
            job.error = "Spyglass stopped while this job was running. Try again."
            job.finished_at = utcnow()
            session.add(job)
        session.commit()
        return len(stuck)


def claim_next(engine: Engine) -> ClaudeJob | None:
    """Mark the oldest queued job running and return it."""
    with _queue_lock, Session(engine) as session:
        job = session.exec(
            select(ClaudeJob).where(ClaudeJob.status == "queued")
            .order_by(ClaudeJob.id)  # type: ignore[arg-type]
        ).first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def set_progress(engine: Engine, job_id: int, progress: str | None) -> None:
    with Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        if job is not None:
            job.progress = progress
            session.add(job)
            session.commit()


def cancel_requested(engine: Engine, job_id: int) -> bool:
    with Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        return bool(job and job.cancel_requested)


# --- the Claude run -------------------------------------------------------------------------


def allowed_tools(kind: str) -> list[str]:
    """The tools a run of this kind may call: Spyglass's own, and nothing else."""
    return [f"mcp__spyglass__{name}" for name in SPYGLASS_TOOLS[kind]]


def denied_tools(settings: Settings) -> list[str]:
    return list(DENIED_TOOLS) + [f"mcp__{settings.obsidian_mcp_server}__{name}"
                                 for name in OBSIDIAN_DENIED]


def _servers_in(path: Path, project: Path | None = None) -> dict:
    """MCP servers in a Claude config file: an .mcp.json, or ~/.claude.json with its user-scope
    servers and, for the given folder, its local-scope ones."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    servers = dict(data.get("mcpServers") or {})
    if project is not None:
        projects = data.get("projects") or {}
        for key in (str(project), project.as_posix()):
            entry = projects.get(key)
            if isinstance(entry, dict):
                servers.update(entry.get("mcpServers") or {})
    return servers


def find_obsidian_server(settings: Settings) -> dict:
    """The Obsidian MCP server's config, which Spyglass uses to have Obsidian move a note.

    Hidden runs ignore the user's settings files, and with them the servers in ~/.claude.json,
    so Spyglass looks the server up itself: the vault's .mcp.json, then ~/.claude.json (local
    scope for the vault, then user scope). Raises ObsidianServerMissing when it is nowhere.
    """
    name = settings.obsidian_mcp_server
    vault = settings.vault_path
    places: list[tuple[Path, Path | None]] = []
    if vault is not None:
        places.append((vault / ".mcp.json", None))
    places.append((Path.home() / ".claude.json", vault))
    for path, project in places:
        server = _servers_in(path, project).get(name)
        if isinstance(server, dict):
            return server
    raise ObsidianServerMissing(
        f"Spyglass could not find your Obsidian MCP server \"{name}\" in the vault's .mcp.json "
        "or in ~/.claude.json. Check its name in Settings (claude mcp list shows it).")


def job_prompt(job_id: int, kind: str, card_id: int) -> str:
    """The run's only message: everything else comes from job_start (the engine contract)."""
    return (
        f"Spyglass background job {job_id} ({kind}) for item #{card_id}. Call the spyglass tool "
        f"job_start with job_id {job_id} first and follow the instructions it returns. Nobody "
        "is watching this run: never ask a question, and end by calling job_finish."
    )


def mcp_config_file(settings: Settings, port: int, kind: str) -> Path:
    """Write the run's MCP servers to a file in the data folder: Spyglass's own, and nothing else.
    The user's Obsidian server is not given to a run, so its settings, which may hold
    its key, are never copied into this file.

    A file rather than a JSON argument: with an npm install, `claude` is a .cmd script, and
    Windows would pass a JSON argument through its command shell, which mangles the quotes.
    """
    servers: dict = {"spyglass": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp/"}}
    path = settings.data_dir / "jobs" / f"{kind}-mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return path


def model_for(settings: Settings, kind: str) -> str:
    return getattr(settings, MODEL_SETTING[kind])


def build_command(settings: Settings, claude: str, kind: str, mcp_config: Path) -> list[str]:
    """The hidden `claude -p` command for one job; the prompt goes in on standard input.

    The run ignores the user's and the vault's settings files (`--setting-sources ""`), so no
    allow rule, plugin or hook of theirs widens or slows it, and loads only the MCP servers
    Spyglass gives it (`--strict-mcp-config`). Of the built-in tools it gets only the reading and
    searching ones (`--tools`). Denied tools stay denied whatever else allows them. The output is streamed JSON: besides the result, it carries Claude's report on how
    much of the user's 5-hour and weekly limits is used.
    """
    return [
        claude, "-p",
        "--model", model_for(settings, kind),
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "dontAsk",
        "--setting-sources", "",
        "--tools", ",".join(BUILT_IN_TOOLS),
        "--allowedTools", ",".join(allowed_tools(kind)),
        "--disallowedTools", ",".join(denied_tools(settings)),
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",
        "--max-turns", str(MAX_TURNS),
        "--no-session-persistence",
    ]


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in DROPPED_ENV:
        env.pop(name, None)
    return env


@dataclass
class RunOutcome:
    """What one Claude run left behind: its exit, its JSON result and how it ended."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def parse_result(stdout: str) -> dict:
    """The JSON result of `--output-format json`, or {} when there is none (the run crashed or
    printed something else). The result is the last JSON object on stdout."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    try:
        value = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_rate_limit(stdout: str) -> dict | None:
    """The last rate-limit report in a streamed run: status, reset time and how much of the
    5-hour and weekly windows is used. None when the run printed none."""
    info = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{") or "rate_limit_event" not in line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("type") == "rate_limit_event":
            info = value.get("rate_limit_info") or info
    return info


def usage_of(info: dict | None) -> tuple[float | None, float | None]:
    """How much of the 5-hour and the weekly window is used (0..1), from a rate-limit report."""
    windows = (info or {}).get("unifiedWindows") or {}
    def used(name: str) -> float | None:
        value = (windows.get(name) or {}).get("utilization")
        return float(value) if isinstance(value, (int, float)) else None
    return used("five_hour"), used("seven_day")


def limit_reset(outcome: "RunOutcome", result: dict, now: datetime | None = None) -> datetime | None:
    """When the user's Claude limit resets, if this run was stopped by one; otherwise None.

    A run stopped by a limit says so in its result ("You've hit your session limit · resets
    3:45pm") and in its rate-limit report (status "rejected", with the reset time)."""
    now = now or utcnow()
    info = parse_rate_limit(outcome.stdout) or {}
    rejected = info.get("status") == "rejected"
    said = " ".join(str(x) for x in [result.get("result") or "", *(result.get("errors") or [])])
    if not rejected and not (result.get("is_error") and _LIMIT_TEXT.search(said)):
        return None
    reset = info.get("resetsAt")
    if isinstance(reset, (int, float)) and reset > now.timestamp():
        return datetime.fromtimestamp(reset, tz=UTC)
    return now + LIMIT_WAIT


def _one_line(text: str) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= REASON_MAX else clean[: REASON_MAX - 1] + "…"


def failure_reason(outcome: RunOutcome, result: dict, timeout_minutes: int) -> str | None:
    """Why a run failed, in words for the item; None when the run itself succeeded."""
    if outcome.cancelled:
        return "Cancelled."
    if outcome.timed_out:
        return f"Claude took longer than {timeout_minutes} minutes, so the run was stopped."
    denied = sorted({d.get("tool_name", "?") for d in result.get("permission_denials") or []
                     if isinstance(d, dict)})
    refused = f" Tools refused: {', '.join(denied)}." if denied else ""
    subtype = result.get("subtype")
    if subtype == "error_max_turns":
        return f"Claude used all {MAX_TURNS} turns without finishing.{refused}"
    if result.get("is_error") or (subtype and subtype != "success"):
        text = result.get("result") or "; ".join(result.get("errors") or []) or str(subtype)
        return _one_line(f"Claude stopped: {text}") + refused
    if not result:
        tail = outcome.stderr.strip().splitlines()[-1:] or outcome.stdout.strip().splitlines()[-1:]
        detail = f": {tail[0]}" if tail else ""
        return _one_line(f"Claude Code did not run (exit code {outcome.returncode}){detail}")
    if outcome.returncode not in (0, None):
        return _one_line(f"Claude Code exited with code {outcome.returncode}.") + refused
    return None


def finish(engine: Engine, job_id: int, outcome: RunOutcome, timeout_minutes: int) -> dict:
    """Close a job after its run: usage, then ok or failed with the reason. A run that ended
    cleanly but never called job_finish fails too: Spyglass cannot tell what it did."""
    result = parse_result(outcome.stdout)
    reason = failure_reason(outcome, result, timeout_minutes)
    with Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        if job is None:
            return {}
        usage = result.get("usage") or {}
        models = list((result.get("modelUsage") or {}).keys())
        job.model = models[0] if models else job.model
        job.usage_five_hour, job.usage_week = usage_of(parse_rate_limit(outcome.stdout))
        job.cost_usd = result.get("total_cost_usd")
        job.duration_ms = result.get("duration_ms")
        job.num_turns = result.get("num_turns")
        job.input_tokens = usage.get("input_tokens")
        job.output_tokens = usage.get("output_tokens")
        if reason is None and not job.reported:
            said = result.get("result") or ""
            reason = _one_line("Claude finished without reporting back to Spyglass"
                               + (f": {said}" if said else "."))
        if reason is None and job.error:
            reason = job.error
        if job.reported and not job.error:
            # The run reported success before it was stopped or ran out of turns or time: the
            # note was written or filed, so the job did its work.
            reason = None
            outcome.cancelled = False
        job.status = "cancelled" if outcome.cancelled else ("failed" if reason else "ok")
        job.error = None if job.status == "ok" else reason
        job.progress = None
        job.finished_at = utcnow()
        session.add(job)
        session.add(RunLog(source=f"claude-job:{job.kind}",
                           status="ok" if job.status == "ok" else "error",
                           detail=f"#{job.card_id}: {job.message if job.status == 'ok' else reason}",
                           started_at=job.started_at or job.created_at,
                           finished_at=job.finished_at))
        session.commit()
        session.refresh(job)
        return job_dict(job)


def requeue_for_limit(engine: Engine, job_id: int, reset: datetime) -> dict:
    """Put a job stopped by the user's Claude limit back in the queue, to run after the reset."""
    with Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        if job is None:
            return {}
        local = reset.astimezone()
        when = local.strftime("%H:%M") if local.date() == datetime.now().astimezone().date() \
            else local.strftime("%a %d %b %H:%M")
        job.status = "queued"
        job.started_at = None
        job.reported = False
        job.error = None
        job.progress = f"Waiting for Claude's usage limit to reset at {when}"
        session.add(job)
        session.commit()
        session.refresh(job)
        return job_dict(job)


def fail(engine: Engine, job_id: int, reason: str) -> dict:
    """Fail a job before any Claude run started (no Claude Code, no vault, Obsidian closed)."""
    with Session(engine) as session:
        job = session.get(ClaudeJob, job_id)
        if job is None:
            return {}
        job.status = "failed"
        job.error = reason
        job.progress = None
        job.finished_at = utcnow()
        session.add(job)
        session.add(RunLog(source=f"claude-job:{job.kind}", status="error",
                           detail=f"#{job.card_id}: {reason}",
                           started_at=job.started_at or job.created_at,
                           finished_at=job.finished_at))
        session.commit()
        session.refresh(job)
        return job_dict(job)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop a run and what it started (MCP servers, shells)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_claude(command: list[str], cwd: Path, timeout_s: float,
               should_stop: Callable[[], bool], prompt: str = "",
               poll_s: float = 1.0) -> RunOutcome:
    """Run one hidden Claude process with the prompt on standard input: no console window,
    stopped on time-out or when should_stop() turns true (cancel, or the service stopping)."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(  # noqa: S603 -- a fixed command; the prompt goes in on stdin
        command, cwd=cwd, env=child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kwargs)
    deadline = time.monotonic() + timeout_s
    # The prompt is written once; later calls only collect output.
    pending_input: str | None = prompt
    finished = False
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(input=pending_input, timeout=poll_s)
                finished = True
                return RunOutcome(proc.returncode, stdout or "", stderr or "")
            except subprocess.TimeoutExpired:
                pending_input = None
                timed_out = time.monotonic() >= deadline
                stopped = should_stop()
                if timed_out or stopped:
                    _kill_tree(proc)
                    finished = True
                    stdout, stderr = _collect(proc)
                    return RunOutcome(proc.returncode, stdout, stderr,
                                      timed_out=timed_out and not stopped, cancelled=stopped)
    finally:
        if not finished:  # an error while waiting must not leave Claude running unwatched
            _kill_tree(proc)


def _collect(proc: subprocess.Popen, timeout_s: float = 10.0) -> tuple[str, str]:
    """What a stopped process printed, without waiting forever for pipes a child still holds."""
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return "", ""
    return stdout or "", stderr or ""
