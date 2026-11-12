"""Tests for the Claude Code route: command, parsing, repair retry, failures and the process cap.

A fake runner stands in for the `claude` process, so nothing here starts a program or calls a model.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from spyglass_service.config import Settings
from spyglass_service.radar import llm_claude
from spyglass_service.radar.llm_claude import (
    RunResult,
    build_command,
    claude_chat_json,
    extract_json,
    failure_message,
    render_prompt,
)
from spyglass_service.radar.llm_errors import LlmUnavailable

SCHEMA = {"name": "t", "strict": True, "schema": {
    "type": "object", "properties": {"a": {"type": "string"}, "n": {"type": "integer"}},
    "required": ["a", "n"], "additionalProperties": False}}
MESSAGES = [{"role": "system", "content": "Be strict."}, {"role": "user", "content": "Go."}]


def settings(tmp_path: Path, **extra) -> Settings:
    """Settings with a fixed command name and a throwaway data folder."""
    return Settings(_env_file=None, data_dir=tmp_path, claude_command="claude", **extra)


def result_line(**fields) -> str:
    """A `--output-format json` result object as one line of standard output."""
    base = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01,
            "usage": {"input_tokens": 3, "output_tokens": 5}}
    return json.dumps({**base, **fields})


class FakeRunner:
    """Returns scripted outputs in order (the last repeats) and records each call."""

    def __init__(self, *outputs: RunResult) -> None:
        """`outputs` are handed out one per call."""
        self.outputs = list(outputs)
        self.calls: list[tuple[list[str], str, Path, float]] = []

    def __call__(self, command, prompt, cwd, timeout_s) -> RunResult:
        """Record the call and return the next scripted output."""
        self.calls.append((command, prompt, cwd, timeout_s))
        index = min(len(self.calls) - 1, len(self.outputs) - 1)
        return self.outputs[index]


def ok(**fields) -> RunResult:
    """A successful run whose JSON result has `fields`."""
    return RunResult(0, result_line(**fields), "")


def test_structured_output_is_returned_and_command_is_locked_down(tmp_path) -> None:
    """The structured payload comes back; the command has every safety flag and no session."""
    runner = FakeRunner(ok(structured_output={"a": "x", "n": 1}))
    out = claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    assert out == {"a": "x", "n": 1}
    command, prompt, cwd, _timeout = runner.calls[0]
    assert command[1] == "-p" and command[command.index("--model") + 1] == "haiku"
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in command
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--output-format") + 1] == "json"
    assert json.loads(command[command.index("--json-schema") + 1])["required"] == ["a", "n"]
    # The instructions are the system prompt file (read back by the provider's cache); the prompt
    # is only what changes from call to call.
    system_file = Path(command[command.index("--system-prompt-file") + 1])
    assert "Be strict." in system_file.read_text(encoding="utf-8") and "Be strict." not in prompt
    assert "Go." in prompt
    assert cwd == tmp_path / "llm_cwd" and cwd.is_dir()


def test_fenced_text_reply_is_parsed(tmp_path) -> None:
    """A reply in a code fence with chatter around it still yields the object."""
    text = 'Here you go:\n```json\n{"a": "y", "n": 2}\n```\nDone.'
    runner = FakeRunner(ok(result=text))
    out = claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    assert out == {"a": "y", "n": 2}


def test_one_repair_retry_then_success(tmp_path) -> None:
    """A reply missing a required key is retried once with a repair instruction."""
    runner = FakeRunner(ok(result='{"a": "only"}'), ok(structured_output={"a": "z", "n": 3}))
    out = claude_chat_json(MESSAGES, SCHEMA, model="sonnet", settings=settings(tmp_path), runner=runner)
    assert out == {"a": "z", "n": 3} and len(runner.calls) == 2
    assert "not usable" in runner.calls[1][1] and "lacks required keys: n" in runner.calls[1][1]


def test_two_unusable_replies_raise_value_error(tmp_path) -> None:
    """Twice without valid JSON is a ValueError (the judging code counts it as malformed)."""
    runner = FakeRunner(ok(result="no json here"))
    with pytest.raises(ValueError, match="no usable JSON"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    assert len(runner.calls) == 2


def test_missing_command_is_unavailable(tmp_path, monkeypatch) -> None:
    """No claude command means LlmUnavailable and no process."""
    monkeypatch.setattr(llm_claude, "find_claude", lambda _s: None)
    runner = FakeRunner(ok())
    with pytest.raises(LlmUnavailable, match="not found"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    assert runner.calls == []


def test_timeout_is_unavailable(tmp_path) -> None:
    """A run the runner reports as timed out becomes LlmUnavailable, without a retry."""
    runner = FakeRunner(RunResult(None, "", "", timed_out=True))
    with pytest.raises(LlmUnavailable, match="took longer"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path),
                         runner=runner, timeout=5)
    assert len(runner.calls) == 1


def test_usage_limit_maps_to_unavailable_with_reset_time(tmp_path) -> None:
    """A usage-limit result names the limit and the reset time."""
    runner = FakeRunner(ok(is_error=True, result="You've hit your session limit · resets 3:45pm"))
    with pytest.raises(LlmUnavailable, match=r"usage limit.*resets 3:45pm"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)


def test_not_signed_in_maps_to_unavailable(tmp_path) -> None:
    """A login failure says to sign in, whether it is in the result or only on stderr."""
    runner = FakeRunner(ok(is_error=True, result="Not logged in · Please run /login"))
    with pytest.raises(LlmUnavailable, match="not signed in"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    crash = FakeRunner(RunResult(1, "", "Error: please log in first"))
    with pytest.raises(LlmUnavailable, match="not signed in"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=crash)


def test_other_failure_message_is_short() -> None:
    """An unknown error is reported in one short line; a success reports none."""
    run = RunResult(0, "", "")
    assert failure_message({"is_error": True, "result": "boom\n  bang"}, run) == "Claude Code failed: boom bang"
    assert failure_message({"is_error": False, "result": "fine"}, run) is None


def test_shim_command_puts_schema_in_prompt(tmp_path, monkeypatch) -> None:
    """A .cmd shim gets no --json-schema flag; the schema and a strict instruction go on stdin."""
    monkeypatch.setattr(llm_claude, "find_claude", lambda _s: "C:/x/claude.cmd")
    runner = FakeRunner(ok(result='{"a": "q", "n": 4}'))
    claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    command, prompt, _cwd, _timeout = runner.calls[0]
    assert "--json-schema" not in command and "validates against this JSON Schema" in prompt


def test_missing_model_is_unavailable(tmp_path) -> None:
    """An empty model name is reported, not passed to the command."""
    with pytest.raises(LlmUnavailable, match="No Claude model"):
        claude_chat_json(MESSAGES, SCHEMA, model="", settings=settings(tmp_path), runner=FakeRunner(ok()))


def test_helpers() -> None:
    """extract_json, render_prompt and build_command behave on plain inputs."""
    assert extract_json('x {"k": 1} y') == {"k": 1}
    with pytest.raises(ValueError):
        extract_json("[1, 2]")
    text = render_prompt([{"role": "user", "content": "hi"}], None)
    assert text == "hi"
    assert "--json-schema" not in build_command("claude", "haiku", None)


def test_at_most_three_processes_run_at_once(tmp_path) -> None:
    """Eight concurrent calls never have more than MAX_PROCESSES runner calls in flight."""
    lock, state = threading.Lock(), {"now": 0, "peak": 0}

    def runner(command, prompt, cwd, timeout_s) -> RunResult:
        """Count calls in flight while pretending to work for a moment."""
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return ok(structured_output={"a": "x", "n": 1})

    cfg = settings(tmp_path)
    threads = [threading.Thread(target=claude_chat_json, args=(MESSAGES, SCHEMA),
                                kwargs={"model": "haiku", "settings": cfg, "runner": runner})
               for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert llm_claude.MAX_PROCESSES == 3 and 1 < state["peak"] <= 3


def test_usage_tally_counts_calls_and_cost(tmp_path) -> None:
    """Each finished call adds to the running totals."""
    llm_claude.USAGE.reset()
    runner = FakeRunner(ok(structured_output={"a": "x", "n": 1}, total_cost_usd=0.5))
    claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path), runner=runner)
    snap = llm_claude.USAGE.snapshot()
    assert snap["calls"] == 1 and snap["cost_usd"] == 0.5 and snap["output_tokens"] == 5
