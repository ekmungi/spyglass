"""Tests for the command-line engines (Claude Code, Codex) and the child-process helper."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from spyglass_service.radar.assist.engines import claude_code, codex_cli
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.engines.process import ChildProcess

from .test_assist_support import clean_assist_env, make_settings  # noqa: F401

MESSAGES = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ans"},
            {"role": "user", "content": "second"}]


class FakeChild:
    """Stands in for ChildProcess: plays scripted output lines (None = idle tick)."""

    instances: list["FakeChild"] = []

    def __init__(self, command, *, cwd, env, stdin_text):
        self.command, self.cwd, self.env, self.stdin_text = command, cwd, env, stdin_text
        self.script = FakeChild.script_for_next
        self.closed = False
        self.stderr_tail = "boom on stderr"
        FakeChild.instances.append(self)

    script_for_next: list = []

    def lines(self, *, timeout_s, tick_s=0.25):
        for line in self.script:
            if isinstance(line, Exception):
                raise line
            yield line

    def close(self):
        self.closed = True


@pytest.fixture
def fake_child(monkeypatch):
    """Replace the process helper in both CLI engines and reset recorded instances."""
    FakeChild.instances = []
    monkeypatch.setattr(claude_code, "ChildProcess", FakeChild)
    monkeypatch.setattr(codex_cli, "ChildProcess", FakeChild)
    return FakeChild


def j(**kw) -> str:
    """One JSON line."""
    return json.dumps(kw) + "\n"


def delta_line(text: str, sid: str = "S1") -> str:
    """A Claude Code partial-message line."""
    return j(type="stream_event", session_id=sid,
             event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})


def cc_engine(tmp_path, monkeypatch, enabled=True):
    """A Claude Code engine whose command lookup succeeds."""
    monkeypatch.setattr(claude_code, "find_claude", lambda s: "claude")
    return claude_code.ClaudeCodeEngine(make_settings(tmp_path), enabled=enabled)


def test_parse_line_reads_session_deltas_and_result():
    state: dict = {}
    first = claude_code.parse_line(delta_line("Hi"), state)
    assert first == [StreamEvent.session("S1"), StreamEvent.delta("Hi")]
    assert claude_code.parse_line(delta_line(" there"), state) == [StreamEvent.delta(" there")]
    assert claude_code.parse_line(j(type="result", is_error=False, session_id="S1"), state) == [
        StreamEvent.done()]
    assert claude_code.parse_line("not json", state) == []


def test_parse_line_falls_back_to_assistant_message_when_no_partials():
    state: dict = {}
    msg = j(type="assistant", message={"content": [{"type": "text", "text": "Whole answer"}]})
    assert claude_code.parse_line(msg, state) == [StreamEvent.delta("Whole answer")]
    state["partials"] = True
    assert claude_code.parse_line(msg, state) == []


def test_parse_line_error_result_is_a_short_error():
    events = claude_code.parse_line(j(type="result", is_error=True, result="You hit your limit"), {})
    assert events[0].kind == "error" and "hit your limit" in events[0].text


def test_command_uses_documented_flags_and_resume():
    engine = claude_code.ClaudeCodeEngine(make_settings(Path(".")), enabled=True)
    args = engine.command("claude", "haiku", "SID")
    for flag in ("-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                 "--setting-sources", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--resume") + 1] == "SID"
    assert "--resume" not in engine.command("claude", "haiku", None)
    assert "--bare" not in args  # --bare would ignore the reader's sign-in


def test_render_prompt_fresh_and_resumed():
    fresh = claude_code.render_prompt("", MESSAGES, resumed=False)
    assert "Reader: first" in fresh and fresh.endswith("second") and "CTX" not in fresh
    assert claude_code.render_prompt("", MESSAGES, resumed=True) == "second"
    # What is new on this turn is sent whether or not the session already holds the earlier turns.
    assert "CTX" in claude_code.render_prompt("CTX", MESSAGES, resumed=True)


def test_claude_code_availability(tmp_path, monkeypatch):
    off = cc_engine(tmp_path, monkeypatch, enabled=False)
    assert off.available()[0] is False and "off" in off.available()[1].lower()
    monkeypatch.setattr(claude_code, "find_claude", lambda s: None)
    missing = claude_code.ClaudeCodeEngine(make_settings(tmp_path), enabled=True)
    assert missing.available() == (False, "The claude command was not found on this computer.")
    assert [m["id"] for m in cc_engine(tmp_path, monkeypatch).models()][:3] == [
        "sonnet", "opus", "haiku"]


def test_claude_code_stream_runs_in_neutral_cwd_and_kills_child(tmp_path, monkeypatch, fake_child):
    fake_child.script_for_next = [None, delta_line("A"), delta_line("B"),
                                  j(type="result", is_error=False, session_id="S1")]
    engine = cc_engine(tmp_path, monkeypatch)
    events = list(engine.stream(system="CTX", messages=MESSAGES[:1], model="haiku"))
    kinds = [e.kind for e in events]
    assert kinds == ["ping", "session", "delta", "delta", "done"]
    child = fake_child.instances[0]
    assert child.cwd == tmp_path / "data" / "assist_cwd" and child.cwd.is_dir()
    assert "ANTHROPIC_API_KEY" not in child.env
    assert "CTX" in Path(child.command[child.command.index("--system-prompt-file") + 1]).read_text(
        encoding="utf-8") and child.closed


def test_claude_code_closing_early_still_closes_child(tmp_path, monkeypatch, fake_child):
    fake_child.script_for_next = [delta_line("A"), delta_line("B")]
    gen = cc_engine(tmp_path, monkeypatch).stream(system="x", messages=MESSAGES[:1], model="haiku")
    next(gen), next(gen)
    gen.close()
    assert fake_child.instances[0].closed


def test_claude_code_timeout_and_silent_exit_are_errors(tmp_path, monkeypatch, fake_child):
    engine = cc_engine(tmp_path, monkeypatch)
    fake_child.script_for_next = [TimeoutError()]
    assert "too long" in list(engine.stream(system="x", messages=MESSAGES[:1], model="m"))[-1].text
    fake_child.script_for_next = []
    last = list(engine.stream(system="x", messages=MESSAGES[:1], model="m"))[-1]
    assert last.kind == "error" and "boom on stderr" in last.text


def test_claude_code_retries_without_session_when_resume_fails(tmp_path, monkeypatch, fake_child):
    scripts = iter([[j(type="result", is_error=True, result="No conversation found")],
                    [delta_line("ok", "NEW"), j(type="result", is_error=False)]])

    def make(*a, **kw):
        fake_child.script_for_next = next(scripts)
        return FakeChild(*a, **kw)

    monkeypatch.setattr(claude_code, "ChildProcess", make)
    events = list(cc_engine(tmp_path, monkeypatch).stream(
        system="x", messages=MESSAGES, model="haiku", session="OLD"))
    assert [e.kind for e in events] == ["session", "delta", "done"]
    assert "--resume" in fake_child.instances[0].command
    assert "--resume" not in fake_child.instances[1].command
    assert "Reader: first" in fake_child.instances[1].stdin_text  # history re-sent in full


def test_claude_code_unavailable_streams_one_error(tmp_path, monkeypatch):
    events = list(cc_engine(tmp_path, monkeypatch, enabled=False).stream(
        system="x", messages=MESSAGES[:1], model="m"))
    assert [e.kind for e in events] == ["error"]


# ---- Codex (untested against a real installation) ------------------------------------------


def test_codex_parse_line_events():
    state: dict = {}
    assert codex_cli.parse_line(j(type="thread.started", thread_id="T1"), state) == [
        StreamEvent.session("T1")]
    item = j(type="item.completed", item={"type": "agent_message", "text": "Hello"})
    assert codex_cli.parse_line(item, state) == [StreamEvent.delta("Hello")]
    assert codex_cli.parse_line(j(type="turn.completed", usage={}), state) == [StreamEvent.done()]
    assert codex_cli.parse_line(j(type="item.completed", item={"type": "reasoning"}), {}) == []
    err = codex_cli.parse_line(j(type="error", message="bad login"), {})
    assert err[0].kind == "error" and "bad login" in err[0].text
    assert codex_cli.parse_line(j(type="turn.completed"), {})[0].kind == "error"


def test_codex_command_and_availability(tmp_path, monkeypatch):
    engine = codex_cli.CodexCliEngine(make_settings(tmp_path), enabled=True)
    args = engine.command("codex", "gpt-x", "T1")
    assert args[:3] == ["codex", "exec", "--json"] and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--model") + 1] == "gpt-x"
    assert args[args.index("resume") + 1] == "T1"
    assert "--model" not in engine.command("codex", "default", None)
    monkeypatch.setattr(codex_cli, "find_codex", lambda: None)
    assert engine.available()[0] is False
    off = codex_cli.CodexCliEngine(make_settings(tmp_path), enabled=False)
    assert off.available()[0] is False


def test_codex_stream_with_fake_process(tmp_path, monkeypatch, fake_child):
    monkeypatch.setattr(codex_cli, "find_codex", lambda: "codex")
    fake_child.script_for_next = [
        j(type="thread.started", thread_id="T1"),
        j(type="item.completed", item={"type": "agent_message", "text": "Answer"}),
        j(type="turn.completed", usage={})]
    engine = codex_cli.CodexCliEngine(make_settings(tmp_path), enabled=True)
    # Codex is off until it can run without file access: switched on, it still never starts.
    refused = list(engine.stream(system="CTX", messages=MESSAGES, model="default"))
    assert [(e.kind, e.text) for e in refused] == [("error", codex_cli.UNSUPPORTED)]
    assert fake_child.instances == []
    # The dormant stream path still parses correctly for the day the engine is allowed again.
    monkeypatch.setattr(engine, "available", engine._available_when_supported)
    events = list(engine.stream(system="CTX", messages=MESSAGES, model="default"))
    assert [e.kind for e in events] == ["session", "delta", "done"]
    assert fake_child.instances[0].closed and "CTX" in fake_child.instances[0].stdin_text


# ---- The real process helper ---------------------------------------------------------------


def test_child_process_feeds_stdin_and_reads_lines(tmp_path):
    code = "import sys; [print(l.strip().upper(), flush=True) for l in sys.stdin]"
    child = ChildProcess([sys.executable, "-c", code], cwd=tmp_path,
                         env=dict(os.environ), stdin_text="a\nb\n")
    try:
        got = [line.strip() for line in child.lines(timeout_s=20) if line is not None]
    finally:
        child.close()
    assert got == ["A", "B"] and child.returncode == 0


def test_child_process_timeout_and_close_kill_the_process(tmp_path):
    child = ChildProcess([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path,
                         env=dict(os.environ), stdin_text="")
    ticks = 0
    with pytest.raises(TimeoutError):
        for line in child.lines(timeout_s=0.6, tick_s=0.1):
            ticks += line is None
    started = time.monotonic()
    child.close()
    assert child.returncode is not None and time.monotonic() - started < 10
    assert ticks >= 1
    child.close()  # safe to call twice


def test_child_process_reports_stderr_tail(tmp_path):
    code = "import sys; sys.stderr.write('bad thing'); sys.exit(3)"
    child = ChildProcess([sys.executable, "-c", code], cwd=tmp_path,
                         env=dict(os.environ), stdin_text="")
    try:
        list(child.lines(timeout_s=20))
        child.close()
    finally:
        child.close()
    assert "bad thing" in child.stderr_tail and child.returncode == 3
