"""Read what a background filing session printed, and decide whether and why it stopped.

The session runs with `--output-format stream-json`: one JSON object per line. The first `init`
line lists the tools, tool servers (with their connection status), plugins and skills the
session actually got; the last `result` line holds the outcome, the cost, the token figures and
every tool call that was refused. From those, plus the run's own report through
`radar_filing_report`, `stop_reason` names the first reason the run did not do its work, in a
fixed order: time limit, usage limit, sign-in, no start at all, vault skills missing, Spyglass
tools missing, Obsidian unreachable, the session's own report, then any other error.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from spyglass_service.claude_jobs import RunOutcome, limit_reset
from spyglass_service.radar.filing_access import SERVER
from spyglass_service.radar.llm_claude import RunResult, failure_message

DETAIL_MAX = 300


@dataclass(frozen=True)
class SessionFacts:
    """What one session reported about itself."""

    started: bool
    tools: tuple[str, ...]
    servers: dict
    plugins: tuple[str, ...]
    skills: tuple[str, ...]
    result: dict
    denials: tuple[str, ...]
    tool_calls: tuple[str, ...]


def _json(line: str) -> dict | None:
    """One output line as an object, or None."""
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _denial(entry: object) -> str:
    """A refused call as "Tool: first part of its input" (one line)."""
    if not isinstance(entry, dict):
        return "?"
    tool = str(entry.get("tool_name") or "?")
    given = entry.get("tool_input") if isinstance(entry.get("tool_input"), dict) else {}
    shown = given.get("command") or given.get("path") or given.get("file_path") or ""
    text = f"{tool}: {shown}" if shown else tool
    return " ".join(text.split())[:200]


def parse_stream(lines: list[str]) -> SessionFacts:
    """The facts in a session's stream-json output (missing parts are empty)."""
    init: dict = {}
    result: dict = {}
    calls: list[str] = []
    for line in lines:
        obj = _json(line.strip())
        if obj is None:
            continue
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init":
            init = obj
        elif kind == "assistant":
            for block in (obj.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append(str(block.get("name") or "?"))
        elif kind == "result":
            result = obj
    servers = {str(s.get("name")): str(s.get("status")) for s in init.get("mcp_servers") or []
               if isinstance(s, dict)}
    return SessionFacts(
        started=bool(init), tools=tuple(str(t) for t in init.get("tools") or []),
        servers=servers,
        plugins=tuple(str(p.get("name")) for p in init.get("plugins") or [] if isinstance(p, dict)),
        skills=tuple(str(s) for s in init.get("skills") or []), result=result,
        denials=tuple(_denial(d) for d in result.get("permission_denials") or []),
        tool_calls=tuple(calls))


def _cut(text: str) -> str:
    """One line of at most DETAIL_MAX characters."""
    return " ".join(str(text).split())[:DETAIL_MAX]


def stop_reason(facts: SessionFacts, *, kind: str, plugin: str, obsidian: str | None,
                timed_out: bool, returncode: int | None, stdout: str, stderr: str,
                report: dict | None, now: datetime) -> tuple[str | None, str | None, datetime | None]:
    """(reason code, one-line detail, retry time) when the run stopped; (None, None, None) when
    it ran. The retry time is set only for a usage limit with a known reset."""
    if timed_out:
        return "time_limit", None, None
    reset = limit_reset(RunOutcome(returncode, stdout, stderr), facts.result, now)
    if reset is not None:
        return "usage_limit", None, reset
    said = failure_message(facts.result, RunResult(returncode, stdout, stderr))
    if said and said.startswith("Your Claude plan's usage limit"):
        return "usage_limit", None, None
    if said and said.startswith("Claude Code is not signed in"):
        return "not_signed_in", None, None
    if not facts.started:
        tail = (stderr.strip().splitlines() or stdout.strip().splitlines() or [""])[-1]
        return "failed", _cut(f"Claude Code did not start (exit code {returncode}). {tail}"), None
    if plugin not in facts.plugins or not any(s.startswith(f"{plugin}:") for s in facts.skills):
        return "skills_missing", _cut(f"The {plugin} skills were not loaded."), None
    if facts.servers.get(SERVER) != "connected":
        return "tools_missing", _cut(f"The Spyglass tools were {facts.servers.get(SERVER, 'missing')}."), None
    if kind == "file" and obsidian and facts.servers.get(obsidian) == "failed":
        return "obsidian_unreachable", None, None
    if report and report.get("status") == "stopped":
        return report.get("reason") or "failed", report.get("detail") or None, None
    if said:
        return "failed", _cut(said), None
    subtype = facts.result.get("subtype")
    if subtype and subtype != "success":
        return "failed", _cut(f"Claude stopped early ({subtype})."), None
    return None, None, None
