"""The OpenAI Codex command line (`codex exec`) as an assistant engine, for ChatGPT plans.

UNTESTED against a real installation: Codex is not installed on the machine this was written
on. It follows OpenAI's public non-interactive-mode documentation, which describes:
  codex exec [flags] "<prompt>" | codex exec -    (prompt from standard input with "-")
  --json                 standard output becomes JSON Lines
  --sandbox read-only    the documented default, set explicitly here
  --skip-git-repo-check  allow running outside a Git repository
  codex exec resume <SESSION_ID> "<prompt>"   continue an earlier session
Events seen with --json: thread.started (thread_id), turn.started, item.started and
item.completed (item.type "agent_message" carries the text; others are reasoning, command
execution and so on), turn.completed (usage), turn.failed and error.
Not confirmed by that page: the `--model` spelling, the `error` / `turn.failed` fields (read
defensively here), and whether `resume` accepts the same flags after it (they are placed before
it). Codex emits whole messages, not token deltas, so the answer arrives in one piece.
"""

import json
import logging
import os
import shutil
from collections.abc import Iterator

from spyglass_service.config import Settings
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.engines.process import ChildProcess
from spyglass_service.radar.assist.engines.safe_args import assert_cmd_safe, valid_model, valid_session

logger = logging.getLogger(__name__)

TIMEOUT_S = 300.0
# "default" means: do not pass --model, let Codex use the model of the reader's plan.
DEFAULT_MODEL = "default"
MODELS: list[dict] = [{"id": DEFAULT_MODEL, "label": "Codex default model"}]
# Why the engine is off: its agent can read files on this computer while reading web text.
UNSUPPORTED = "not supported yet: this engine cannot be run without file access"


def find_codex() -> str | None:
    """The codex command on PATH, or None."""
    return shutil.which("codex")


def parse_line(line: str, state: dict) -> list[StreamEvent]:
    """Turn one JSONL line from `codex exec --json` into events (see the module docstring)."""
    try:
        obj = json.loads(line)
    except ValueError:
        return []
    if not isinstance(obj, dict):
        return []
    kind = obj.get("type")
    if kind == "thread.started" and obj.get("thread_id"):
        return [StreamEvent.session(str(obj["thread_id"]))]
    if kind == "item.completed":
        item = obj.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            state["text"] = True
            return [StreamEvent.delta(str(item["text"]))]
        return []
    if kind == "turn.completed":
        state["finished"] = True
        if state.get("text"):
            return [StreamEvent.done()]
        return [StreamEvent.error("Codex finished without an answer.")]
    if kind in ("turn.failed", "error"):
        state["finished"] = True
        raw = obj.get("message") or (obj.get("error") or {}).get("message") or "Codex reported an error"
        return [StreamEvent.error(f"Codex: {' '.join(str(raw).split())[:240]}")]
    return []


class CodexCliEngine:
    """Answers with the reader's installed Codex command (not tested; see the module docstring)."""

    id = "codex_cli"
    label = "Codex CLI (your ChatGPT plan)"
    kind = "cli"

    def __init__(self, settings: Settings, *, enabled: bool | None = None,
                 models: list[dict] | None = None) -> None:
        """`enabled` overrides settings.assist_codex_cli_enabled; `models` adds named models."""
        self._settings = settings
        self.enabled = settings.assist_codex_cli_enabled if enabled is None else enabled
        self._models = list(models) if models else list(MODELS)

    def models(self) -> list[dict]:
        """The offered models; Codex's own default first."""
        return list(self._models)

    def available(self) -> tuple[bool, str | None]:
        """Never usable for now, whatever the switch says (see `UNSUPPORTED`).

        Codex runs an agent that can read local files (`--sandbox read-only` still allows
        reading), and the assistant hands it untrusted article text. Until a mode with no tools
        and no file access is confirmed, the engine reports itself unavailable and never starts.
        """
        return False, UNSUPPORTED

    def _available_when_supported(self) -> tuple[bool, str | None]:
        """The availability rule to restore once a tool-free mode exists."""
        if not self.enabled:
            return False, "Switched off. Turn it on to use your Codex installation."
        if find_codex() is None:
            return False, "The codex command was not found on this computer."
        return True, None

    def command(self, codex: str, model: str, session: str | None) -> list[str]:
        """The argument list for one turn; the prompt is read from standard input ("-").

        Raises ValueError for a model name or session id that is not a plain token, and for a
        batch-file command whose arguments carry cmd metacharacters.
        """
        if model and not valid_model(model):
            raise ValueError("That model name is not valid.")
        if session and not valid_session(session):
            raise ValueError("That session id is not valid.")
        args = [codex, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check"]
        if model and model != DEFAULT_MODEL:
            args += ["--model", model]
        if session:
            args += ["resume", session]
        args = args + ["-"]
        assert_cmd_safe(args)
        return args

    def stream(
        self,
        *,
        system: str,
        messages: list[dict],
        model: str,
        session: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream one answer (arrives as a whole message); kills the process on close."""
        ok, reason = self.available()
        if not ok:
            yield StreamEvent.error(reason or "Codex is not available.")
            return
        if model and not valid_model(model):
            yield StreamEvent.error("That model name is not valid for Codex.")
            return
        if session and not valid_session(session):
            session = None  # a stored id of an unknown shape is never passed on; start afresh
        cwd = self._settings.data_dir / "assist_cwd"
        cwd.mkdir(parents=True, exist_ok=True)
        latest = messages[-1]["content"] if messages else ""
        if session:
            prompt = latest
        else:
            history = "\n\n".join(
                f"{'Reader' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in messages[:-1])
            prompt = "\n\n".join(p for p in (
                f"<instructions_and_context>\n{system}\n</instructions_and_context>",
                f"<earlier_conversation>\n{history}\n</earlier_conversation>" if history else "",
                latest) if p)
        child = ChildProcess(self.command(find_codex() or "codex", model, session), cwd=cwd,
                             env=dict(os.environ), stdin_text=prompt)
        state: dict = {}
        try:
            for line in child.lines(timeout_s=TIMEOUT_S):
                if line is None:
                    yield StreamEvent.ping()
                    continue
                for event in parse_line(line, state):
                    yield event
                    if event.kind in ("done", "error"):
                        return
            if not state.get("finished"):
                tail = " ".join(child.stderr_tail.split())[-200:]
                yield StreamEvent.error(f"Codex stopped without an answer. {tail}".strip())
        except TimeoutError:
            yield StreamEvent.error("Codex took too long and was stopped.")
        finally:
            child.close()
