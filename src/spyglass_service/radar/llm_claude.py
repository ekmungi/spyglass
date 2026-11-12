"""Structured-JSON model calls through the reader's own installed Claude Code command.

`claude_chat_json` is the Claude counterpart of `openrouter.chat_json`: it takes OpenAI-style
messages and a `{"name", "schema"}` response schema and returns one parsed JSON object. Each call
runs `claude -p` once, headless, with the prompt on standard input (a Windows command line cannot
carry tens of thousands of characters) and the reader's own sign-in; Spyglass never reads or
stores a login.

Flags used (all present in Claude Code 2.1.x; see `claude -p --help`):
  -p, --output-format json      answer once; one JSON result object on standard output
  --model <alias>               sonnet, haiku, opus or a full model name
  --system-prompt <short text>  replaces the coding-assistant prompt; the real instructions go on
                                standard input
  --json-schema <schema>        structured output (skipped for .cmd/.bat shims, whose argument
                                quoting is unreliable; the schema then goes in the prompt)
  --tools ""                    no tools at all
  --setting-sources ""          no user, project or local settings (no hooks or allow rules)
  --strict-mcp-config           no MCP servers (none are passed)
  --disable-slash-commands      no skills or commands
  --permission-mode dontAsk     anything that would ask is refused
  --no-session-persistence      the call leaves nothing in the reader's Claude session history

It runs in an empty folder under the data directory and with `ANTHROPIC_API_KEY` removed from the
environment, so it bills the reader's plan. At most `MAX_PROCESSES` run at once.
"""

import json
import logging
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spyglass_service.claude_jobs import _kill_tree, find_claude, parse_result
from spyglass_service.radar import usage
from spyglass_service.radar.claude_env import quiet_env
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.llm_system import prune_system_files, write_system_file
from spyglass_service.radar.usage_parse import claude_tokens

logger = logging.getLogger(__name__)

# Claude processes alive at once. Each one is a full Claude Code start-up, so more would only
# thrash the machine and trip the plan's rate limit sooner.
MAX_PROCESSES = 3
# One call must finish within this many seconds; a stuck command is killed with its children.
TIMEOUT_S = 240.0
# The flag-level system prompt stays short and free of quotes; the real instructions go on stdin.
_SYSTEM = (
    "You are a careful analyst working for one reader. You have no tools. "
    "You answer with structured JSON only."
)
_SLOT = threading.BoundedSemaphore(MAX_PROCESSES)

_LIMIT_TEXT = re.compile(
    r"hit your .{0,40}limit|usage limit|rate.?limit|limit reached|too many requests", re.I)
_AUTH_TEXT = re.compile(
    r"not logged in|please run /login|\blog ?in\b|authentication|unauthori[sz]ed|invalid api key"
    r"|oauth", re.I)
_RESET_TEXT = re.compile(r"resets?\s+(?:at\s+)?([^·|\n]{3,40})", re.I)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


@dataclass(frozen=True)
class RunResult:
    """What one `claude -p` process left behind."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


# (command, stdin text, working folder, timeout seconds) -> RunResult. Tests inject a fake.
Runner = Callable[[list[str], str, Path, float], RunResult]


class UsageTally:
    """Thread-safe running total of the Claude calls made by this process."""

    def __init__(self) -> None:
        """Start every counter at zero."""
        self._lock = threading.Lock()
        self.calls = 0
        self.errors = 0
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_tokens = 0
        self.seconds = 0.0

    def reset(self) -> None:
        """Zero the counters."""
        with self._lock:
            self.calls = 0
            self.errors = 0
            self.cost_usd = 0.0
            self.input_tokens = 0
            self.output_tokens = 0
            self.cache_tokens = 0
            self.seconds = 0.0

    def add(self, result: dict, seconds: float) -> None:
        """Record one finished call from its JSON result and its wall time."""
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        with self._lock:
            self.calls += 1
            self.errors += 1 if result.get("is_error") else 0
            self.cost_usd += float(result.get("total_cost_usd") or 0.0)
            self.input_tokens += int(usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("output_tokens") or 0)
            self.cache_tokens += int(usage.get("cache_creation_input_tokens") or 0) + int(
                usage.get("cache_read_input_tokens") or 0)
            self.seconds += seconds

    def snapshot(self) -> dict:
        """The counters as a plain dict. `cost_usd` is the list price the command reports, which
        is what the same work would cost on the API; a plan is not charged per call."""
        with self._lock:
            return {"calls": self.calls, "errors": self.errors,
                    "cost_usd": round(self.cost_usd, 4), "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens, "cache_tokens": self.cache_tokens,
                    "seconds": round(self.seconds, 1)}


USAGE = UsageTally()


def default_runner(command: list[str], prompt: str, cwd: Path, timeout_s: float) -> RunResult:
    """Run `command` with `prompt` on standard input; kill the whole process tree on timeout."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(  # noqa: S603 -- a fixed command; the prompt goes on stdin
            command, cwd=cwd, env=quiet_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kwargs)
    except OSError as exc:
        raise LlmUnavailable(f"Claude Code could not be started: {exc}") from exc
    try:
        out, err = proc.communicate(prompt, timeout=timeout_s)
        return RunResult(proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return RunResult(None, out or "", err or "", timed_out=True)


def schema_body(schema: dict) -> dict:
    """The bare JSON Schema inside a `{"name", "schema"}` wrapper (or the dict itself)."""
    inner = schema.get("schema")
    return inner if isinstance(inner, dict) else schema


def build_command(claude: str, model: str, schema: dict | None,
                  system_file: Path | None = None) -> list[str]:
    """The argument list for one call; `schema` is the bare JSON Schema, or None to leave it out.

    With `system_file` the instructions come from that file (see `llm_system`); without it the
    short built-in system prompt is passed on the command line.
    """
    system = ["--system-prompt-file", str(system_file)] if system_file else ["--system-prompt", _SYSTEM]
    args = [
        claude, "-p", "--model", model, "--output-format", "json",
        *system,
        "--tools", "", "--setting-sources", "", "--strict-mcp-config",
        "--disable-slash-commands", "--permission-mode", "dontAsk",
        "--no-session-persistence",
    ]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    return args


def system_text(messages: list[dict]) -> str:
    """The system messages joined: the instructions and the reader's profile."""
    return "\n\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")


def render_prompt(messages: list[dict], schema: dict | None, *, with_system: bool = True) -> str:
    """The text for standard input: system messages as instructions, then the conversation.

    With `schema` given (the command was not passed `--json-schema`) a strict instruction and
    the schema are appended. `with_system` False leaves the instructions out (they are in the
    system prompt file).
    """
    system = system_text(messages) if with_system else ""
    rest = [m for m in messages if m.get("role") != "system"]
    parts = []
    if system:
        parts.append(f"<instructions>\n{system}\n</instructions>")
    for message in rest:
        text = str(message.get("content", ""))
        parts.append(text if message.get("role") == "user" else f"Earlier reply: {text}")
    if schema is not None:
        parts.append(
            "Reply with one JSON object that validates against this JSON Schema and nothing "
            "else: no commentary and no code fence.\n" + json.dumps(schema))
    return "\n\n".join(parts)


def extract_json(text: str) -> dict:
    """Parse a JSON object out of a reply, tolerating a fenced block or text around it."""
    candidates = [text.strip()]
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("the reply holds no JSON object")


def validate(payload: dict, schema: dict) -> dict:
    """Return `payload` if it carries every key the schema requires, else raise ValueError."""
    required = schema_body(schema).get("required") or []
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"the JSON object lacks required keys: {', '.join(missing)}")
    return payload


def _one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace and cut `text` to `limit` characters."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def failure_message(result: dict, run: RunResult) -> str | None:
    """A short reader-facing reason when the run failed (limit, sign-in, other); else None."""
    status = result.get("api_error_status")
    said = " ".join(str(x) for x in [result.get("result") or "", *(result.get("errors") or [])])
    failed = bool(result.get("is_error")) or (not result and run.returncode not in (0, None))
    if not failed:
        return None
    text = said if result else f"{run.stderr} {run.stdout}"
    if status == 429 or _LIMIT_TEXT.search(text):
        reset = _RESET_TEXT.search(text)
        when = f"; it resets {reset.group(1).strip()}" if reset else ""
        return f"Your Claude plan's usage limit was reached{when}."
    if status in (401, 403) or _AUTH_TEXT.search(text):
        return "Claude Code is not signed in. Open a terminal, run `claude` and sign in."
    return f"Claude Code failed: {_one_line(text) or 'no details given'}"


def _payload(result: dict) -> dict:
    """The model's JSON object from a successful result: structured output, else the text."""
    structured = result.get("structured_output")
    if isinstance(structured, dict):
        return structured
    return extract_json(str(result.get("result") or ""))


def _run_once(runner: Runner, command: list[str], prompt: str, cwd: Path,
              timeout_s: float, model: str = "") -> tuple[dict, RunResult]:
    """One process under the concurrency cap; returns its parsed JSON result and raw output."""
    with _SLOT:
        started = time.perf_counter()
        run = runner(command, prompt, cwd, timeout_s)
        seconds = time.perf_counter() - started
    if run.timed_out:
        raise LlmUnavailable(f"Claude Code took longer than {int(timeout_s)} seconds and was stopped.")
    result = parse_result(run.stdout)
    USAGE.add(result, seconds)
    logger.debug("claude call finished in %.1fs (exit %s)", seconds, run.returncode)
    reason = failure_message(result, run)
    if reason:
        raise LlmUnavailable(reason)
    usage.note_call(provider="claude_code", model=model, tokens=claude_tokens(result),
                    duration_ms=int(seconds * 1000))
    return result, run


def claude_chat_json(
    messages: list[dict],
    schema: dict,
    *,
    model: str,
    settings,
    runner: Runner | None = None,
    timeout: float = TIMEOUT_S,
) -> dict:
    """Ask the installed Claude Code for one JSON object matching `schema`.

    messages: OpenAI-style messages (system first). schema: `{"name", "schema"}` or a bare
    schema. model: an alias such as "haiku" or "sonnet". settings: supplies `claude_command` and
    `data_dir`. runner: replaces the process launch (tests). Raises LlmUnavailable when the
    command is missing, not signed in, rate limited or too slow, and ValueError when the reply
    is not a valid object even after one repair request.
    """
    if not model:
        raise LlmUnavailable("No Claude model is set for this job.")
    claude = find_claude(settings)
    if claude is None:
        raise LlmUnavailable("The claude command was not found on this computer.")
    body = schema_body(schema)
    use_flag = not claude.lower().endswith((".cmd", ".bat"))
    cwd = Path(settings.data_dir) / "llm_cwd"
    try:
        cwd.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LlmUnavailable(f"Claude Code's working folder could not be created: {exc}") from exc
    # The instructions and the profile are the same for every call of a kind, so they are the
    # system prompt, where the provider's cache can reuse them; only the batch is sent as the prompt.
    # If the file cannot be written the instructions go on standard input instead (no length limit
    # there), which costs the cache reuse but not the call.
    try:
        system_file: Path | None = write_system_file(cwd, f"{_SYSTEM}\n\n{system_text(messages)}")
    except OSError as exc:
        logger.warning("could not write the system prompt file; sending the instructions inline: %s", exc)
        system_file = None
    prune_system_files(cwd)  # never raises
    command = build_command(claude, model, body if use_flag else None, system_file)
    prompt = render_prompt(messages, None if use_flag else body, with_system=system_file is None)
    run_it = runner or default_runner
    problem = ""
    for attempt in (1, 2):
        stdin_text = prompt
        if attempt == 2:
            stdin_text += (
                f"\n\nYour previous reply was not usable ({problem}). Reply again with one JSON "
                "object that validates against the schema and nothing else.")
        result, _run = _run_once(run_it, command, stdin_text, cwd, timeout, model)
        try:
            return validate(_payload(result), schema)
        except ValueError as exc:
            problem = str(exc)
            logger.warning("claude reply unusable (attempt %d): %s", attempt, problem)
    raise ValueError(f"Claude returned no usable JSON: {problem}")
