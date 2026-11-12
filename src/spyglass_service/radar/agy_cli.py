"""Shared pieces for running Google's Antigravity command line (`agy`) headless and safely.

Both the assistant engine and the bulk judging route use this module. It holds the safety gate
that reads Antigravity's own settings file before every call, the one command shape Spyglass
ever runs, and the reading of the command's streamed JSON events.

How a call works (Antigravity CLI headless documentation, checked against version 1.5.0):
  agy --input-format stream-json --output-format stream-json --disable-slash-commands
      [--model <slug>] [--json-schema <schema>]
The prompt goes on standard input as one line, {"event": "user", "message": {"content": ...}},
and standard input is then closed, so the process answers that one turn and exits. A Windows
command line cannot carry a long article, and standard input has no such limit. The output is
one JSON event per line: "init" (its `permission_mode` is checked), "step_update" (text arrives
as `text_delta` on `agent_response` steps; `tool` steps are tool calls) and one "result".

Antigravity's agent has tools (web search, files, commands, a browser). In its default asking
mode a headless run cannot ask, so any tool that needs permission is refused. Spyglass only uses
the command when its settings keep that default (`check_settings`), never passes a flag that
widens permissions (`assert_no_widening`), and stops a run at its first tool call (`stop_reason`).
"""

import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

from spyglass_service.radar.assist.engines.safe_args import assert_cmd_safe, valid_model

logger = logging.getLogger(__name__)

# "default" in a model list means: pass no --model flag and let Antigravity use its own default.
DEFAULT_MODEL = "default"
SETTINGS_RELATIVE = Path(".gemini") / "antigravity-cli" / "settings.json"
WORKDIR_NAME = "agy_cwd"

UNSAFE_REASON = "Antigravity is set to allow tools without asking, so Spyglass will not use it."
UNREADABLE_REASON = (
    "Spyglass could not read Antigravity's settings file, so it will not use Antigravity.")
TRUSTED_REASON = (
    "Spyglass's working folder for Antigravity is marked as trusted in Antigravity, so Spyglass "
    "will not use it. Remove that folder from Antigravity's trusted workspaces.")
UNSAFE_RUNTIME = (
    "Antigravity reported that it runs without asking before using tools, so Spyglass stopped it.")
TOOL_REFUSED = "Antigravity tried to use a tool and was refused. The answer was discarded."
NOT_SIGNED_IN = "Antigravity is not signed in. Open a terminal, run agy once and sign in."
USAGE_LIMIT = "Your Google plan's Antigravity usage limit was reached. Try again later."
UNKNOWN_MODEL = "Antigravity does not know that model. Pick another one in the settings."
NOT_FOUND = "The agy command was not found on this computer."

# Settings values that keep Antigravity asking before it uses a tool. Anything else widens it.
_SAFE_AGENT_MODES = frozenset({"", "default"})
_SAFE_TOOL_PERMISSIONS = frozenset({"request-review", "strict"})
# The `permission_mode` an "init" event may report: the asking default, or the stricter one.
_SAFE_RUNTIME_MODES = frozenset({"request-review", "strict"})
# Flags that would widen what the agent may do or where it runs. Never part of a command.
_WIDENING_FLAGS = ("--dangerously-skip-permissions", "--mode", "--add-dir", "--remote-agent",
                   "--remote-control", "--agent", "--prompt-interactive", "-i", "--project",
                   "--new-project")
# Secrets of other services are removed from the child's environment; Google's own sign-in
# variables stay, because Antigravity may be set up to use them.
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)
_KEEP_PREFIXES = ("GEMINI_", "GOOGLE_")

_DENIED_TEXT = re.compile(r"auto-denied|cannot prompt for|denied_actions", re.I)
_AUTH_TEXT = re.compile(
    r"authentication required|not authenticated|not signed in|please (?:sign|log) ?in|"
    r"unauthori[sz]ed|login required", re.I)
_LIMIT_TEXT = re.compile(
    r"quota|usage limit|rate.?limit|resource.?exhausted|too many requests|\b429\b|"
    r"limit reached|out of credits", re.I)
_MODEL_TEXT = re.compile(r"invalid model selection|not recognized as a known model", re.I)


def settings_file() -> Path:
    """Where Antigravity keeps its user settings."""
    return Path.home() / SETTINGS_RELATIVE


def find_agy() -> str | None:
    """The agy command: PATH first, then the Windows installer's folder; None when absent."""
    found = shutil.which("agy")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if sys.platform == "win32" and local:
        candidate = Path(local) / "agy" / "bin" / "agy.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def workdir_for(settings) -> Path:
    """The empty folder every run starts in (created when missing)."""
    path = Path(settings.data_dir) / WORKDIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _values(data: dict, key: str) -> list:
    """Every value stored under `key`, matching the key without regard to case."""
    return [value for name, value in data.items() if isinstance(name, str)
            and name.lower() == key.lower()]


def _short(value: object) -> str:
    """A setting value for a reason sentence, cut short so a long value is never echoed."""
    text = " ".join(str(value).split())
    return text if len(text) <= 40 else text[:39] + "…"


def _unsafe_setting(data: dict) -> str | None:
    """Which setting widens Antigravity's permissions, in a few words; None when none does."""
    for permissions in _values(data, "permissions"):
        if not isinstance(permissions, dict):
            return "the permissions setting is not in the expected form"
        for allow in _values(permissions, "allow"):
            if allow is None:
                continue
            if not isinstance(allow, list):
                return "permissions.allow is not a list"
            if allow:
                return f"permissions.allow has {len(allow)} rule(s)"
    for mode in _values(data, "agentMode"):
        if mode is not None and (not isinstance(mode, str)
                                 or mode.strip().lower() not in _SAFE_AGENT_MODES):
            return f"agentMode is {_short(mode)}"
    for policy in _values(data, "toolPermission"):
        if policy is not None and (not isinstance(policy, str)
                                   or policy.strip().lower() not in _SAFE_TOOL_PERMISSIONS):
            return f"toolPermission is {_short(policy)}"
    for wide in _values(data, "allowNonWorkspaceAccess"):
        if wide not in (None, False):
            return "allowNonWorkspaceAccess is on"
    return None


def _is_trusted(entries: object, workdir: Path) -> bool:
    """Whether `workdir` is one of the trusted folders or lies inside one."""
    if not isinstance(entries, list):
        return False
    target = os.path.normcase(str(workdir.resolve()))
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        folder = os.path.normcase(str(Path(entry).resolve()))
        if target == folder or target.startswith(folder.rstrip("\\/") + os.sep):
            return True
    return False


def check_settings(path: Path, workdir: Path | None = None) -> tuple[bool, str | None]:
    """The safety gate: (True, None) when Antigravity keeps asking before it uses a tool.

    Unsafe, with a plain reason: any allow rule under permissions.allow (of any action type), an
    agentMode other than the default, a toolPermission other than request-review or strict,
    allowNonWorkspaceAccess switched on, a file that cannot be parsed as a JSON object, or a
    `workdir` listed among the trusted workspaces. A missing file means Antigravity's defaults,
    which ask.
    """
    if not path.exists():
        return True, None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        logger.warning("could not parse the Antigravity settings file")
        return False, UNREADABLE_REASON
    if not isinstance(data, dict):
        return False, UNREADABLE_REASON
    problem = _unsafe_setting(data)
    if problem:
        return False, f"{UNSAFE_REASON} ({problem})"
    if workdir is not None and any(_is_trusted(v, workdir)
                                   for v in _values(data, "trustedWorkspaces")):
        return False, TRUSTED_REASON
    return True, None


def ready(settings) -> tuple[bool, str | None]:
    """Whether a bulk call can be tried now: the command exists and the gate passes.

    Creates nothing: the working folder is only named, for the trusted-workspace check.
    """
    if find_agy() is None:
        return False, NOT_FOUND
    data_dir = getattr(settings, "data_dir", None)
    workdir = Path(data_dir) / WORKDIR_NAME if data_dir else None
    return check_settings(settings_file(), workdir)


def assert_no_widening(command: list[str]) -> None:
    """Refuse a command that carries any flag widening Antigravity's permissions (ValueError)."""
    for arg in command[1:]:
        for flag in _WIDENING_FLAGS:
            if arg == flag or arg.startswith(flag + "="):
                raise ValueError(f"The flag {flag} widens Antigravity's permissions and is "
                                 "never used.")


def build_command(agy: str, *, model: str | None, schema_json: str | None = None) -> list[str]:
    """The argument list for one call; the prompt itself goes on standard input.

    `model` "default", "" or None passes no --model flag. Raises ValueError for a model name
    that is not a plain token, for a widening flag and for a batch-file shim whose arguments
    carry command-shell metacharacters.
    """
    args = [agy, "--input-format", "stream-json", "--output-format", "stream-json",
            "--disable-slash-commands"]
    if model and model != DEFAULT_MODEL:
        if not valid_model(model):
            raise ValueError("That model name is not valid for Antigravity.")
        args += ["--model", model]
    if schema_json is not None:
        args += ["--json-schema", schema_json]
    assert_no_widening(args)
    assert_cmd_safe(args)
    return args


def user_message_line(prompt: str) -> str:
    """The one standard-input line that carries a prompt."""
    return json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"


def agy_env() -> dict[str, str]:
    """The child's environment: this process's, minus other services' secrets."""
    return {name: value for name, value in os.environ.items()
            if not _SECRET_NAME.search(name) or name.upper().startswith(_KEEP_PREFIXES)}


def parse_event(line: str) -> dict | None:
    """One output line as an event dict with an "event" key, or None for anything else."""
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) and isinstance(value.get("event"), str) else None


def stop_reason(event: dict) -> str | None:
    """Why a run must be stopped at this event, or None.

    An "init" event whose permission_mode is not the asking default (or strict) means the agent
    could act without asking. A step that calls a tool or a subagent means the model tried to act
    instead of answering; with web text in the prompt that is the sign of an injected instruction.
    """
    kind = event.get("event")
    if kind == "init":
        mode = (event.get("init") or {}).get("permission_mode")
        if mode is not None and str(mode).strip().lower() not in _SAFE_RUNTIME_MODES:
            return UNSAFE_RUNTIME
        return None
    if kind == "step_update":
        step = event.get("step_update") or {}
        if step.get("step_type") == "tool" or any(
                key in step for key in ("tool_name", "tool_info", "subagent_info")):
            return TOOL_REFUSED
    return None


def answer_text(event: dict) -> str:
    """The answer text a "step_update" event adds, or ""."""
    if event.get("event") != "step_update":
        return ""
    step = event.get("step_update") or {}
    if step.get("step_type") != "agent_response":
        return ""
    text = step.get("text_delta")
    return text if isinstance(text, str) else ""


def _one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace and cut `text` to `limit` characters."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def classify_failure(text: str) -> str | None:
    """A reader-facing sentence for a known failure named in `text`, or None."""
    if _DENIED_TEXT.search(text):
        return TOOL_REFUSED
    if _MODEL_TEXT.search(text):
        return UNKNOWN_MODEL
    if _AUTH_TEXT.search(text):
        return NOT_SIGNED_IN
    if _LIMIT_TEXT.search(text):
        return USAGE_LIMIT
    return None


def result_problem(result: dict, stderr: str) -> str | None:
    """Why a "result" payload cannot be used, or None when it succeeded without a refused tool.

    A successful result whose response is empty is not a problem here: the caller decides what an
    empty answer means.
    """
    if result.get("denied_actions"):
        return TOOL_REFUSED
    if result.get("status") == "SUCCESS":
        return None
    said = f"{result.get('error') or ''} {stderr}"
    return classify_failure(said) or (
        f"Antigravity failed: {_one_line(str(result.get('error') or stderr or 'no details given'))}")
