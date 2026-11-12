"""Tests for the Antigravity safety gate, command building and stream reading (radar/agy_cli.py).

No test runs the real `agy` program or reads the real Antigravity settings file: every check
gets its own settings file in a temporary folder.
"""

import json
from pathlib import Path

import pytest

from spyglass_service.radar import agy_cli
from spyglass_service.radar.agy_cli import (
    TOOL_REFUSED,
    UNREADABLE_REASON,
    UNSAFE_REASON,
    UNSAFE_RUNTIME,
    assert_no_widening,
    build_command,
    check_settings,
    classify_failure,
    parse_event,
    result_problem,
    stop_reason,
    user_message_line,
)


def write(tmp_path: Path, value) -> Path:
    """Write `value` as the settings file (a str is written verbatim) and return its path."""
    path = tmp_path / "settings.json"
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return path


# ---- the settings gate ---------------------------------------------------------------------

def test_missing_settings_file_means_the_safe_defaults(tmp_path):
    assert check_settings(tmp_path / "absent.json") == (True, None)


@pytest.mark.parametrize("value", [
    {"trustedWorkspaces": []},
    {"permissions": {"allow": [], "deny": ["command(rm)"], "ask": ["command(*)"]}},
    {"agentMode": ""}, {"agentMode": "default"}, {"agentMode": None},
    {"toolPermission": "request-review"}, {"toolPermission": "strict"},
    {"allowNonWorkspaceAccess": False},
])
def test_default_asking_settings_pass(tmp_path, value):
    assert check_settings(write(tmp_path, value)) == (True, None)


@pytest.mark.parametrize("rule", [
    "read_file(*)", "write_file(src/)", "read_url(google.com)", "execute_url(*)",
    "command(git)", "unsandboxed(*)", "mcp(linter/*)", "anything at all",
])
def test_any_allow_rule_of_any_action_type_makes_it_unavailable(tmp_path, rule):
    ok, reason = check_settings(write(tmp_path, {"permissions": {"allow": [rule]}}))
    assert ok is False
    assert reason.startswith(UNSAFE_REASON)


@pytest.mark.parametrize("value", [
    {"agentMode": "auto"}, {"agentMode": "accept-edits"}, {"agentMode": "plan"},
    {"agentMode": "something-new"}, {"agentMode": 3},
    {"toolPermission": "always-proceed"}, {"toolPermission": "proceed-in-sandbox"},
    {"toolPermission": "whatever"}, {"toolPermission": ["request-review"]},
    {"allowNonWorkspaceAccess": True}, {"allowNonWorkspaceAccess": "yes"},
    {"permissions": {"allow": "command(git)"}}, {"permissions": ["allow"]},
    # Keys are matched without regard to case, as a Go JSON reader would match them.
    {"ToolPermission": "always-proceed"}, {"AGENTMODE": "auto"},
    {"Permissions": {"Allow": ["command(git)"]}},
])
def test_every_widening_setting_makes_it_unavailable(tmp_path, value):
    ok, reason = check_settings(write(tmp_path, value))
    assert ok is False
    assert reason.startswith(UNSAFE_REASON)


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", "", "null", "\x00\x01"])
def test_unparseable_settings_make_it_unavailable(tmp_path, text):
    assert check_settings(write(tmp_path, text)) == (False, UNREADABLE_REASON)


def test_a_settings_file_with_a_byte_order_mark_is_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"agentMode": ""}).encode())
    assert check_settings(path) == (True, None)


def test_a_trusted_working_folder_makes_it_unavailable(tmp_path):
    workdir = tmp_path / "data" / "agy_cwd"
    workdir.mkdir(parents=True)
    trusted = write(tmp_path, {"trustedWorkspaces": [str(tmp_path / "data")]})
    ok, reason = check_settings(trusted, workdir)
    assert ok is False and "trusted" in reason
    other = write(tmp_path, {"trustedWorkspaces": [str(tmp_path / "elsewhere"), 7]})
    assert check_settings(other, workdir) == (True, None)


def test_the_reason_never_echoes_a_long_setting_value(tmp_path):
    ok, reason = check_settings(write(tmp_path, {"agentMode": "x" * 500}))
    assert ok is False and len(reason) < 200


# ---- the command ---------------------------------------------------------------------------

def test_command_reads_the_prompt_from_stdin_as_stream_json():
    cmd = build_command("agy.exe", model="gemini-3.8-flash-medium")
    assert cmd[:6] == ["agy.exe", "--input-format", "stream-json", "--output-format",
                       "stream-json", "--disable-slash-commands"]
    assert cmd[-2:] == ["--model", "gemini-3.8-flash-medium"]
    assert "-p" not in cmd  # the prompt never travels on the command line


def test_default_model_means_no_model_flag_and_schema_is_passed():
    cmd = build_command("agy.exe", model="default", schema_json='{"type":"object"}')
    assert "--model" not in cmd
    assert cmd[-2:] == ["--json-schema", '{"type":"object"}']
    assert "--model" not in build_command("agy.exe", model=None)


@pytest.mark.parametrize("model", ["--dangerously-skip-permissions", "-x", "a b", "", "a;b"])
def test_invalid_model_names_are_refused(model):
    if model == "":
        assert "--model" not in build_command("agy.exe", model=model)
        return
    with pytest.raises(ValueError):
        build_command("agy.exe", model=model)


@pytest.mark.parametrize("model", [None, "default", "gemini-4-carbon-high"])
def test_built_commands_never_carry_a_permission_widening_flag(model):
    cmd = build_command("agy.exe", model=model, schema_json='{"a":1}')
    assert "--dangerously-skip-permissions" not in " ".join(cmd)
    for flag in ("--mode", "--add-dir", "--remote-agent", "--remote-control", "--agent",
                 "--prompt-interactive", "--sandbox", "-i", "--project"):
        assert not any(arg == flag or arg.startswith(flag + "=") for arg in cmd)


@pytest.mark.parametrize("arg", [
    "--dangerously-skip-permissions", "--mode", "--mode=auto", "--add-dir", "--add-dir=C:/",
    "--remote-agent", "--remote-control", "--agent", "-i", "--prompt-interactive",
])
def test_assert_no_widening_refuses_each_widening_flag(arg):
    with pytest.raises(ValueError):
        assert_no_widening(["agy.exe", "--output-format", "stream-json", arg])


def test_assert_no_widening_accepts_the_normal_command():
    assert_no_widening(build_command("agy.exe", model="gemini-3.8-flash-medium"))


def test_batch_file_shim_with_metacharacters_is_refused():
    with pytest.raises(ValueError):
        build_command("agy.cmd", model=None, schema_json='{"a":"b"}')


def test_user_message_line_is_one_json_line():
    line = user_message_line('line one\nline "two"')
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == {"event": "user",
                                "message": {"content": 'line one\nline "two"'}}


# ---- reading the stream --------------------------------------------------------------------

def test_parse_event_ignores_non_events():
    assert parse_event("not json") is None
    assert parse_event("[1]") is None
    assert parse_event('{"no_event": 1}') is None
    assert parse_event('{"event": "init", "init": {}}') == {"event": "init", "init": {}}


def test_stop_reason_for_a_widened_runtime_mode_and_for_tool_steps():
    assert stop_reason({"event": "init", "init": {"permission_mode": "request-review"}}) is None
    assert stop_reason({"event": "init", "init": {"permission_mode": "strict"}}) is None
    assert stop_reason({"event": "init", "init": {}}) is None
    assert stop_reason({"event": "init", "init": {"permission_mode": "always-proceed"}}) \
        == UNSAFE_RUNTIME
    tool = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE",
                                                   "tool_name": "search_web"}}
    assert stop_reason(tool) == TOOL_REFUSED
    sub = {"event": "step_update", "step_update": {"step_type": "x", "subagent_info": {}}}
    assert stop_reason(sub) == TOOL_REFUSED
    text = {"event": "step_update", "step_update": {"step_type": "agent_response",
                                                   "text_delta": "hi"}}
    assert stop_reason(text) is None


def test_classify_failure_names_each_known_problem():
    denied = ('jetski: no output produced - a tool required the "read_file" permission that '
              "headless mode cannot prompt for, so it was auto-denied.")
    assert classify_failure(denied) == TOOL_REFUSED
    assert "not signed in" in classify_failure("error: authentication required")
    assert "usage limit" in classify_failure("RESOURCE_EXHAUSTED: quota exceeded")
    assert "does not know" in classify_failure(
        'invalid model selection (--model "zz"): model zz is not recognized')
    assert classify_failure("something unrelated") is None


def test_result_problem_for_denials_and_failed_status():
    assert result_problem({"status": "SUCCESS", "response": "ok"}, "") is None
    assert result_problem({"status": "SUCCESS", "response": "",
                           "denied_actions": [{"action": "command"}]}, "") == TOOL_REFUSED
    assert "not signed in" in result_problem(
        {"status": "ERROR", "error": "authentication required"}, "")
    generic = result_problem({"status": "CANCELED", "error": "x" * 900}, "")
    assert generic.startswith("Antigravity failed") and len(generic) < 300


def test_env_for_the_child_drops_other_services_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-one")
    monkeypatch.setenv("SPYGLASS_SLACK_BOT_TOKEN", "secret-two")
    monkeypatch.setenv("GEMINI_API_KEY", "kept-for-agy")
    monkeypatch.setenv("PATH", "/bin")
    env = agy_cli.agy_env()
    assert "OPENROUTER_API_KEY" not in env and "SPYGLASS_SLACK_BOT_TOKEN" not in env
    assert env["GEMINI_API_KEY"] == "kept-for-agy" and env["PATH"] == "/bin"


def test_ready_needs_the_command_and_a_passing_gate(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(agy_cli, "find_agy", lambda: None)
    assert agy_cli.ready(SimpleNamespace(data_dir=tmp_path)) == (False, agy_cli.NOT_FOUND)
    monkeypatch.setattr(agy_cli, "find_agy", lambda: "agy.exe")
    monkeypatch.setattr(agy_cli, "settings_file", lambda: tmp_path / "absent.json")
    assert agy_cli.ready(SimpleNamespace()) == (True, None)
    unsafe = write(tmp_path, {"toolPermission": "always-proceed"})
    monkeypatch.setattr(agy_cli, "settings_file", lambda: unsafe)
    ok, reason = agy_cli.ready(SimpleNamespace(data_dir=tmp_path))
    assert ok is False and reason.startswith(UNSAFE_REASON)
    assert not (tmp_path / agy_cli.WORKDIR_NAME).exists()  # a readiness check creates nothing


def test_find_agy_uses_path_then_the_installer_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(agy_cli.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert agy_cli.find_agy() is None
    exe = tmp_path / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    found = agy_cli.find_agy()
    assert found is None or Path(found) == exe  # the installer folder is a Windows location
    monkeypatch.setattr(agy_cli.shutil, "which", lambda name: "/usr/bin/agy")
    assert agy_cli.find_agy() == "/usr/bin/agy"
