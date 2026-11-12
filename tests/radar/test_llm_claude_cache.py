"""Tests that a bulk Claude call keeps its instructions in the system prompt file, byte for byte the
same from call to call, so the provider can read them from its cache.
"""

import json
import os
import time
from pathlib import Path

from spyglass_service.config import Settings
from spyglass_service.radar import llm_claude
from spyglass_service.radar.claude_env import quiet_env
from spyglass_service.radar.llm_claude import RunResult, build_command, claude_chat_json
from spyglass_service.radar.llm_system import prune_system_files, write_system_file

SCHEMA = {"name": "t", "strict": True, "schema": {
    "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
    "additionalProperties": False}}
RESULT = json.dumps({"type": "result", "is_error": False, "structured_output": {"a": "x"},
                     "usage": {"input_tokens": 1, "output_tokens": 1}})


def settings(tmp_path: Path) -> Settings:
    """Settings with a fixed command name and a throwaway data folder."""
    return Settings(_env_file=None, data_dir=tmp_path, claude_command="claude")


class Recorder:
    """A fake `claude` process that keeps what it was given."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.calls: list[tuple[list[str], str, Path]] = []

    def __call__(self, command, prompt, cwd, timeout_s) -> RunResult:
        """Record the call; the system prompt file is read now, before any pruning."""
        self.calls.append((command, prompt, cwd))
        path = command[command.index("--system-prompt-file") + 1]
        self.files = getattr(self, "files", []) + [Path(path).read_text(encoding="utf-8")]
        return RunResult(0, RESULT, "")


def ask(tmp_path, recorder, system="RUBRIC and PROFILE", user="batch 1"):
    """One call with the given system and user messages."""
    return claude_chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}], SCHEMA,
        model="haiku", settings=settings(tmp_path), runner=recorder)


def test_instructions_go_in_the_system_prompt_file_and_only_the_batch_on_stdin(tmp_path):
    recorder = Recorder()
    ask(tmp_path, recorder)
    command, prompt, _cwd = recorder.calls[0]
    assert "--system-prompt" not in command
    assert "RUBRIC and PROFILE" in recorder.files[0]
    assert "RUBRIC and PROFILE" not in prompt and "batch 1" in prompt


def test_two_calls_with_the_same_instructions_share_one_identical_file(tmp_path):
    recorder = Recorder()
    ask(tmp_path, recorder, user="batch 1")
    ask(tmp_path, recorder, user="batch 2")
    first, second = (c[0][c[0].index("--system-prompt-file") + 1] for c in recorder.calls)
    assert first == second and recorder.files[0] == recorder.files[1]


def test_different_instructions_get_a_different_file(tmp_path):
    recorder = Recorder()
    ask(tmp_path, recorder, system="profile A")
    ask(tmp_path, recorder, system="profile B")
    paths = {c[0][c[0].index("--system-prompt-file") + 1] for c in recorder.calls}
    assert len(paths) == 2


def test_build_command_without_a_file_keeps_the_short_flag_prompt():
    command = build_command("claude", "haiku", None)
    assert "--system-prompt" in command and "--system-prompt-file" not in command
    with_file = build_command("claude", "haiku", None, Path("p.txt"))
    assert with_file[with_file.index("--system-prompt-file") + 1] == "p.txt"
    assert "--system-prompt" not in with_file


def test_write_system_file_is_content_addressed_and_idempotent(tmp_path):
    first = write_system_file(tmp_path, "hello")
    second = write_system_file(tmp_path, "hello")
    assert first == second and first.read_text(encoding="utf-8") == "hello"
    assert write_system_file(tmp_path, "other") != first


def test_prune_removes_only_old_system_files(tmp_path):
    old = write_system_file(tmp_path, "old")
    fresh = write_system_file(tmp_path, "fresh")
    keep = tmp_path / "notes.txt"
    keep.write_text("x")
    past = time.time() - 10 * 86400
    os.utime(old, (past, past))
    os.utime(keep, (past, past))
    assert prune_system_files(tmp_path, max_age_days=3) == 1
    assert not old.exists() and fresh.exists() and keep.exists()


def test_quiet_env_switches_off_memory_and_instruction_files(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-travel")
    env = quiet_env()
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert "ANTHROPIC_API_KEY" not in env


def test_the_default_runner_uses_the_quiet_environment(monkeypatch, tmp_path):
    seen = {}

    class Proc:
        """A stand-in process."""

        returncode = 0

        def communicate(self, prompt, timeout=None):
            return RESULT, ""

    def fake_popen(command, **kwargs):
        seen["env"] = kwargs["env"]
        return Proc()

    monkeypatch.setattr(llm_claude.subprocess, "Popen", fake_popen)
    llm_claude.default_runner(["claude"], "hi", tmp_path, 5.0)
    assert seen["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
