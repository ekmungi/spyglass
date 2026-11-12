# ruff: noqa: F811
"""Tests that a failure to write or prune the system prompt file never breaks a call."""

import json
import threading
from pathlib import Path

from spyglass_service.config import Settings
from spyglass_service.radar.assist.engines import claude_code
from spyglass_service.radar.llm_claude import RunResult, claude_chat_json
from spyglass_service.radar.llm_system import prune_system_files, write_system_file

from .test_assist_cli import cc_engine, delta_line, fake_child, j  # noqa: F401
from .test_assist_support import clean_assist_env  # noqa: F401

SCHEMA = {"name": "t", "schema": {"type": "object", "properties": {"a": {"type": "string"}},
                                   "required": ["a"]}}
RESULT = json.dumps({"type": "result", "is_error": False, "structured_output": {"a": "x"}})
MESSAGES = [{"role": "system", "content": "RUBRIC"}, {"role": "user", "content": "batch"}]


def settings(tmp_path: Path) -> Settings:
    """Settings with a fixed command name and a throwaway data folder."""
    return Settings(_env_file=None, data_dir=tmp_path, claude_command="claude")


def test_two_writers_of_the_same_content_both_succeed(tmp_path):
    paths: list[Path] = []
    errors: list[BaseException] = []
    gate = threading.Barrier(8)

    def write() -> None:
        """Write the same text once all the writers are ready."""
        try:
            gate.wait()
            paths.append(write_system_file(tmp_path, "same text"))
        except BaseException as exc:  # noqa: BLE001 -- the test reports it below
            errors.append(exc)

    workers = [threading.Thread(target=write) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not errors and len(set(paths)) == 1
    assert paths[0].read_text(encoding="utf-8") == "same text"
    assert [p.name for p in tmp_path.iterdir()] == [paths[0].name]  # no partial files left


def test_a_failed_replace_is_success_when_the_file_already_holds_the_same_text(tmp_path, monkeypatch):
    real = Path.replace

    def replace(self, target):
        """Another writer wins the race, then this replace fails as Windows does."""
        winner = self.with_name("winner.tmp")
        winner.write_text("same text")
        real(winner, target)
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", replace)
    path = write_system_file(tmp_path, "same text")
    assert path.read_text(encoding="utf-8") == "same text"
    assert not list(tmp_path.glob("*.tmp"))


def test_a_failed_replace_is_retried_once(tmp_path, monkeypatch):
    real, calls = Path.replace, []

    def replace(self, target):
        """Fail the first time only."""
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("in use")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    assert write_system_file(tmp_path, "text").read_text(encoding="utf-8") == "text"
    assert len(calls) == 2 and not list(tmp_path.glob("*.tmp"))


def test_a_replace_that_keeps_failing_raises_oserror_and_leaves_no_partial_file(tmp_path, monkeypatch):
    def replace(self, target):
        """Always fail."""
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", replace)
    try:
        write_system_file(tmp_path, "text")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    assert not list(tmp_path.glob("*.tmp"))


def test_a_prune_that_raises_is_ignored(tmp_path, monkeypatch):
    def glob(self, pattern):
        """The folder cannot be listed."""
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", glob)
    assert prune_system_files(tmp_path) == 0


def test_a_bulk_call_passes_the_instructions_inline_when_the_file_cannot_be_written(tmp_path, monkeypatch):
    def broken(folder, text):
        """The disk refuses the write."""
        raise OSError("disk full")

    monkeypatch.setattr("spyglass_service.radar.llm_claude.write_system_file", broken)
    seen: list[tuple[list[str], str]] = []

    def runner(command, prompt, cwd, timeout_s):
        """Record what the process would have been given."""
        seen.append((command, prompt))
        return RunResult(0, RESULT, "")

    assert claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path),
                            runner=runner) == {"a": "x"}
    command, prompt = seen[0]
    assert "--system-prompt-file" not in command and "--system-prompt" in command
    assert "RUBRIC" in prompt and "batch" in prompt  # the instructions travel on standard input


def test_a_bulk_call_ignores_a_prune_that_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "glob", lambda self, pattern: (_ for _ in ()).throw(OSError("denied")))
    runner = lambda command, prompt, cwd, timeout_s: RunResult(0, RESULT, "")  # noqa: E731
    assert claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=settings(tmp_path),
                            runner=runner) == {"a": "x"}


def test_a_chat_turn_reports_a_plain_error_when_the_file_cannot_be_written(tmp_path, monkeypatch, fake_child):
    def broken(folder, text):
        """The disk refuses the write."""
        raise OSError("disk full")

    monkeypatch.setattr(claude_code, "write_system_file", broken)
    events = list(cc_engine(tmp_path, monkeypatch).stream(
        system="ROLE", messages=[{"role": "user", "content": "q"}], model="haiku"))
    assert events[-1].kind == "error" and "instructions" in events[-1].text
    assert not fake_child.instances  # no process was started
