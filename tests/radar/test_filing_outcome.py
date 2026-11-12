"""Tests for reading a filing session's output and naming why it stopped (radar/filing_outcome.py)."""

import json
from datetime import UTC, datetime, timedelta

from spyglass_service.radar.filing_outcome import parse_stream, stop_reason

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def init(*, plugins=("vault-tool",), skills=("vault-tool:ingest",), spyglass="connected",
         obsidian="connected") -> str:
    """An init line."""
    return json.dumps({"type": "system", "subtype": "init", "tools": ["Read", "Skill"],
                       "mcp_servers": [{"name": "spyglass_filing", "status": spyglass},
                                       {"name": "obsidian-vault", "status": obsidian}],
                       "plugins": [{"name": p} for p in plugins], "skills": list(skills)})


def result(**fields) -> str:
    """A result line."""
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "total_cost_usd": 0.4, "usage": {"input_tokens": 10, "output_tokens": 5},
                       **fields})


def reason(lines, *, kind="file", timed_out=False, returncode=0, stderr="", report=None):
    """The (code, detail, retry) for some output lines."""
    facts = parse_stream(lines)
    return stop_reason(facts, kind=kind, plugin="vault-tool", obsidian="obsidian-vault",
                       timed_out=timed_out, returncode=returncode, stdout="\n".join(lines),
                       stderr=stderr, report=report, now=NOW)


def test_the_facts_list_tools_servers_plugins_calls_and_refusals():
    call = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf x"}}]}})
    denied = result(permission_denials=[{"tool_name": "Bash", "tool_input": {"command": "rm\n-rf x"}}])
    facts = parse_stream([init(), "not json", call, denied])
    assert facts.started and facts.servers == {"spyglass_filing": "connected",
                                               "obsidian-vault": "connected"}
    assert facts.plugins == ("vault-tool",) and facts.tool_calls == ("Bash",)
    assert facts.denials == ("Bash: rm -rf x",)


def test_a_clean_run_has_no_stop_reason():
    assert reason([init(), result()]) == (None, None, None)


def test_each_stop_reason_in_its_order():
    assert reason([init()], timed_out=True)[0] == "time_limit"
    assert reason([], returncode=1, stderr="boom")[0] == "failed"
    assert reason([init(plugins=()), result()])[0] == "skills_missing"
    assert reason([init(skills=("other:thing",)), result()])[0] == "skills_missing"
    assert reason([init(spyglass="failed"), result()])[0] == "tools_missing"
    assert reason([init(obsidian="failed"), result()])[0] == "obsidian_unreachable"
    # A plan run does not need Obsidian.
    assert reason([init(obsidian="failed"), result()], kind="plan")[0] is None
    report = {"status": "stopped", "reason": "obsidian_unreachable", "detail": "vault_list failed"}
    assert reason([init(), result()], report=report)[:2] == ("obsidian_unreachable",
                                                            "vault_list failed")
    assert reason([init(), result(subtype="error_max_turns")])[0] == "failed"


def test_a_usage_limit_carries_its_reset_time():
    reset = NOW + timedelta(hours=2)
    event = json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": "rejected", "resetsAt": reset.timestamp()}})
    code, _detail, retry = reason([init(), event, result(is_error=True, result="limit")])
    assert code == "usage_limit" and retry == reset


def test_a_usage_limit_said_in_words_is_recognised():
    code, _d, retry = reason([init(), result(is_error=True,
                                             result="You've hit your session limit")])
    assert code == "usage_limit"


def test_not_signed_in_is_recognised():
    line = result(is_error=True, result="Invalid API key · Please run /login")
    assert reason([init(), line])[0] == "not_signed_in"
