"""Tests for bulk judging through Antigravity (radar/llm_agy.py) and its place in the provider chain.

The process launch is replaced by fake runners and a fake child process; no test runs `agy`.
"""

import json
import threading
import time

import pytest

from spyglass_service.config import Settings
from spyglass_service.radar import llm_agy, llm_chain
from spyglass_service.radar.agy_cli import TOOL_REFUSED, UNSAFE_REASON, UNSAFE_RUNTIME
from spyglass_service.radar.llm_agy import RunResult, agy_chat_json, default_runner
from spyglass_service.radar.llm_chain import Cooldowns, model_for_provider, provider_order
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.llm_route import routed_chat_json

SCHEMA = {"name": "triage", "schema": {"type": "object", "required": ["items"],
                                        "properties": {"items": {"type": "array"}}}}
MESSAGES = [{"role": "system", "content": "Judge these items."},
            {"role": "user", "content": "1. A headline"}]


def ev(kind: str, **payload) -> str:
    """One stream-json output line."""
    return json.dumps({"event": kind, **payload})


def stream(*, structured=None, response: str = "", status: str = "SUCCESS", mode="request-review",
           extra_lines: tuple = (), **result_extra) -> str:
    """A whole run's standard output."""
    result = {"status": status, "response": response, **result_extra}
    if structured is not None:
        result["structured_output"] = structured
    lines = [ev("init", init={"permission_mode": mode}), *extra_lines, ev("result", result=result)]
    return "\n".join(lines) + "\n"


class Runner:
    """A fake runner returning scripted results and recording each call."""

    def __init__(self, *results: RunResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, command, stdin_text, cwd, timeout_s) -> RunResult:
        self.calls.append((command, stdin_text))
        return self.results.pop(0)


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    """Settings with the command found and a safe (absent) Antigravity settings file."""
    monkeypatch.setattr(llm_agy, "find_agy", lambda: "agy.exe")
    monkeypatch.setattr(llm_agy, "settings_file", lambda: tmp_path / "none.json")
    return Settings(_env_file=None, data_dir=tmp_path / "data")


def ok_run(stdout: str, stderr: str = "") -> RunResult:
    """A run that exited normally."""
    return RunResult(0, stdout, stderr)


# ---- agy_chat_json -------------------------------------------------------------------------

def test_structured_output_is_returned_and_the_schema_goes_as_a_flag(settings):
    runner = Runner(ok_run(stream(structured={"items": [1, 2]})))
    assert agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=runner) == {
        "items": [1, 2]}
    command, stdin_text = runner.calls[0]
    assert "--json-schema" in command and "--model" not in command
    assert "--dangerously-skip-permissions" not in command
    sent = json.loads(stdin_text)["message"]["content"]
    assert "must not use any tool" in sent and "Judge these items." in sent


def test_model_flag_and_text_reply_parsed_when_no_structured_output(settings):
    runner = Runner(ok_run(stream(response='Here: ```json\n{"items": []}\n```')))
    result = agy_chat_json(MESSAGES, SCHEMA, model="gemini-3.8-flash-medium",
                           settings=settings, runner=runner)
    assert result == {"items": []}
    assert runner.calls[0][0][-4:-2] == ["--model", "gemini-3.8-flash-medium"]


def test_one_repair_retry_then_value_error(settings):
    runner = Runner(ok_run(stream(response="not json")), ok_run(stream(response='{"items": [3]}')))
    assert agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=runner) == {
        "items": [3]}
    assert "previous reply was not usable" in runner.calls[1][1]
    bad = Runner(ok_run(stream(response='{"other": 1}')), ok_run(stream(response="still bad")))
    with pytest.raises(ValueError):
        agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=bad)


def test_large_schema_goes_into_the_prompt_instead(settings):
    big = {"name": "big", "schema": {"type": "object", "required": ["items"],
                                     "description": "x" * 9000}}
    runner = Runner(ok_run(stream(structured={"items": []})))
    agy_chat_json(MESSAGES, big, model="", settings=settings, runner=runner)
    command, stdin_text = runner.calls[0]
    assert "--json-schema" not in command
    assert "validates against this JSON Schema" in json.loads(stdin_text)["message"]["content"]


def test_schema_with_an_empty_enum_value_goes_into_the_prompt(settings):
    # Gemini refuses a structured-output schema whose enum holds "" (seen live: INVALID_ARGUMENT
    # "enum[6]: cannot be empty"), and the triage schema uses "" for "no section".
    schema = {"name": "t", "schema": {"type": "object", "required": ["items"], "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "section": {"type": "string", "enum": ["models", ""]}}}}}}}
    runner = Runner(ok_run(stream(response='{"items": [{"section": ""}]}')))
    assert agy_chat_json(MESSAGES, schema, model="", settings=settings, runner=runner) == {
        "items": [{"section": ""}]}
    command, stdin_text = runner.calls[0]
    assert "--json-schema" not in command
    assert '"enum": ["models", ""]' in json.loads(stdin_text)["message"]["content"]


def test_flag_compatible_schema_check():
    assert llm_agy.flag_compatible({"type": "object", "properties": {
        "a": {"enum": ["x", "y"]}, "b": {"items": [{"enum": [1, 2]}]}}}) is True
    assert llm_agy.flag_compatible({"properties": {"a": {"items": {"enum": ["x", ""]}}}}) is False
    assert llm_agy.flag_compatible({"anyOf": [{"enum": [""]}]}) is False


def test_a_finish_step_from_structured_output_is_not_a_tool_call(settings):
    # Seen live: with --json-schema the stream carries a step of type "finish" with no tool name.
    finish = ev("step_update", step_update={"step_type": "finish", "state": "DONE"})
    runner = Runner(ok_run(stream(extra_lines=(finish,), structured={"items": [7]})))
    assert agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=runner) == {
        "items": [7]}


@pytest.mark.parametrize("run, expected", [
    (ok_run(stream(response="", status="ERROR", error="authentication required")),
     "not signed in"),
    (ok_run(stream(status="ERROR", error="RESOURCE_EXHAUSTED: quota exceeded")), "usage limit"),
    (ok_run(stream(response="", denied_actions=[{"action": "read_file"}])), TOOL_REFUSED),
    (ok_run("", "jetski: no output produced - a tool ... so it was auto-denied."), TOOL_REFUSED),
    (ok_run(stream(extra_lines=(ev("step_update", step_update={
        "step_type": "tool", "tool_name": "search_web"}),), structured={"items": []})),
     TOOL_REFUSED),
    (ok_run(stream(mode="always-proceed", structured={"items": []})), UNSAFE_RUNTIME),
    (RunResult(None, "", "", timed_out=True), "longer than"),
    (RunResult(None, "", "", stopped=TOOL_REFUSED), TOOL_REFUSED),
    (RunResult(1, "", "crashed"), "stopped without an answer"),
])
def test_failures_are_llm_unavailable(settings, run, expected):
    with pytest.raises(LlmUnavailable) as caught:
        agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=Runner(run))
    assert expected in str(caught.value)


def test_missing_command_and_unsafe_settings_are_unavailable(tmp_path, settings, monkeypatch):
    monkeypatch.setattr(llm_agy, "find_agy", lambda: None)
    with pytest.raises(LlmUnavailable, match="agy command"):
        agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=Runner())
    monkeypatch.setattr(llm_agy, "find_agy", lambda: "agy.exe")
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps({"permissions": {"allow": ["command(git)"]}}), encoding="utf-8")
    monkeypatch.setattr(llm_agy, "settings_file", lambda: unsafe)
    runner = Runner()
    with pytest.raises(LlmUnavailable) as caught:
        agy_chat_json(MESSAGES, SCHEMA, model="", settings=settings, runner=runner)
    assert str(caught.value).startswith(UNSAFE_REASON) and runner.calls == []


def test_at_most_two_processes_run_at_once(settings):
    lock = threading.Lock()
    active = {"now": 0, "peak": 0}

    def slow(command, stdin_text, cwd, timeout_s):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.05)
        with lock:
            active["now"] -= 1
        return ok_run(stream(structured={"items": []}))

    threads = [threading.Thread(target=agy_chat_json, args=(MESSAGES, SCHEMA),
                                kwargs={"model": "", "settings": settings, "runner": slow})
               for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert active["peak"] == 2 == llm_agy.MAX_PROCESSES


# ---- the default runner --------------------------------------------------------------------

class FakeChild:
    """Stands in for ChildProcess inside the default runner."""

    last: "FakeChild | None" = None
    script: list = []

    def __init__(self, command, *, cwd, env, stdin_text):
        self.stdin_text, self.closed = stdin_text, False
        self.stderr_tail, self.returncode = "err text", 0
        FakeChild.last = self

    def lines(self, *, timeout_s, tick_s=0.25):
        for line in FakeChild.script:
            if isinstance(line, Exception):
                raise line
            yield line

    def close(self):
        self.closed = True


def test_default_runner_stops_at_the_first_tool_call(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_agy, "ChildProcess", FakeChild)
    tool = ev("step_update", step_update={"step_type": "tool", "tool_name": "run_command"})
    FakeChild.script = [ev("init", init={}) + "\n", None, tool + "\n", "never read\n"]
    run = default_runner(["agy.exe"], "line\n", tmp_path, 5.0)
    assert run.stopped == TOOL_REFUSED and "never read" not in run.stdout
    assert FakeChild.last.closed is True and FakeChild.last.stdin_text == "line\n"


def test_default_runner_timeout_kills_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_agy, "ChildProcess", FakeChild)
    FakeChild.script = ["partial\n", TimeoutError()]
    run = default_runner(["agy.exe"], "line\n", tmp_path, 5.0)
    assert run.timed_out is True and FakeChild.last.closed is True


def test_default_runner_collects_a_normal_run(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_agy, "ChildProcess", FakeChild)
    FakeChild.script = [stream(structured={"items": []})]
    run = default_runner(["agy.exe"], "line\n", tmp_path, 5.0)
    assert run.returncode == 0 and run.stderr == "err text" and '"result"' in run.stdout


# ---- the provider chain --------------------------------------------------------------------

def chain_settings(tmp_path, **overrides) -> Settings:
    """Settings for the chain tests."""
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def test_antigravity_is_a_provider_with_its_own_model(tmp_path):
    settings = chain_settings(tmp_path, radar_llm_provider="antigravity",
                              radar_llm_fallback="openrouter",
                              radar_antigravity_model="gemini-3.8-flash-medium")
    assert provider_order(settings) == ["antigravity", "openrouter"]
    assert model_for_provider(settings, "antigravity", "triage") == "gemini-3.8-flash-medium"
    assert model_for_provider(chain_settings(tmp_path), "antigravity", "digest") == ""
    with pytest.raises(ValueError):
        model_for_provider(settings, "antigravity", "poet")


def test_chain_readiness_and_status_row_for_antigravity(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_chain, "_agy_ready", lambda s: (False, "The agy command was not found"))
    settings = chain_settings(tmp_path, radar_llm_fallback="antigravity")
    rows = {r["name"]: r for r in llm_chain.status(settings, cooldowns=Cooldowns())}
    assert rows["antigravity"]["label"].startswith("Antigravity")
    assert rows["antigravity"]["available"] is False and rows["antigravity"]["position"] == 2
    monkeypatch.setattr(llm_chain, "_agy_ready", lambda s: (True, None))
    assert llm_chain.provider_ready(settings, "antigravity") == (True, None)


def test_route_sends_antigravity_calls_to_the_agy_function(tmp_path):
    settings = chain_settings(tmp_path, radar_llm_provider="antigravity",
                              radar_llm_fallback="openrouter",
                              radar_antigravity_model="gemini-4-carbon-medium")
    seen = []

    def agy_call(messages, schema, *, model, settings):
        seen.append(model)
        return {"items": ["agy"]}

    out = routed_chat_json(settings, "triage", MESSAGES, SCHEMA, openrouter_call=None,
                           agy_call=agy_call, cooldowns=Cooldowns())
    assert out == {"items": ["agy"]} and seen == ["gemini-4-carbon-medium"]


def test_route_falls_back_when_antigravity_is_unavailable(tmp_path):
    settings = chain_settings(tmp_path, radar_llm_provider="antigravity",
                              radar_llm_fallback="openrouter")

    def agy_call(messages, schema, *, model, settings):
        raise LlmUnavailable(TOOL_REFUSED)

    def openrouter_call(settings, model, messages, schema):
        return {"items": ["openrouter", model]}

    out = routed_chat_json(settings, "triage", MESSAGES, SCHEMA, openrouter_call=openrouter_call,
                           agy_call=agy_call, cooldowns=Cooldowns())
    assert out == {"items": ["openrouter", settings.radar_triage_model]}
