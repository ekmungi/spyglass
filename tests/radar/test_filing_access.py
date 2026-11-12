"""Tests for what a background filing session may use (radar/filing_access.py)."""

import json

import pytest

from spyglass_service.radar import filing_access as fa

LAUNCHERS = ['bash "C:/Local/vault-tool/vault-tool"']
# Example look-up commands; the real list is configuration (SPYGLASS_RADAR_FILING_TOOL_COMMANDS).
COMMANDS = ("lookup folder", "lookup template", "lookup version")
WRITING = ("vault_write", "vault_patch", "radar_mark_filed", "radar_filing_ask",
           "radar_filing_applied", "Write", "Edit", "MultiEdit", "NotebookEdit")
NEVER = ("vault_delete", "vault_move", "vault_copy", "vault_append", "command_execute",
         "WebFetch", "WebSearch", "PowerShell", "Task", "Agent")


@pytest.fixture(autouse=True)
def vault_tool(monkeypatch):
    """The owner's launcher name and look-up commands, as the environment would set them."""
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL", "vault-tool")
    monkeypatch.setenv("SPYGLASS_RADAR_FILING_TOOL_COMMANDS", ", ".join(COMMANDS))


def names(rules: list[str]) -> set[str]:
    """The bare tool names in a rule list (server prefix and Bash pattern dropped)."""
    return {r.split("__")[-1].split("(")[0] for r in rules}


@pytest.mark.parametrize("kind", fa.KINDS)
def test_delete_move_rename_web_and_shell_are_never_allowed(kind):
    allowed = fa.allowed_tools(kind, obsidian="obsidian-vault", launchers=LAUNCHERS)
    denied = fa.denied_tools(kind, obsidian="obsidian-vault")
    assert not names(allowed) & set(NEVER)
    assert set(NEVER) <= names(denied)
    # The shell is allowed only as the vault tool's read-only look-up commands, by exact prefix.
    shell = [r for r in allowed if r.startswith("Bash")]
    assert shell and all(r.startswith('Bash(bash "C:/Local/vault-tool/vault-tool" ') for r in shell)
    assert all(r.endswith(":*)") for r in shell)
    assert {r.split('vault-tool" ')[1][:-3] for r in shell} == set(COMMANDS)
    assert not any(cmd in r for r in shell for cmd in ("convert", "scaffold", "write", "delete"))
    # Read-only shell commands Claude Code would allow inside the vault are denied by name.
    for reader in ("ls", "cat", "head", "cd", "printenv"):
        assert f"Bash({reader}:*)" in denied


def test_a_plan_run_can_never_hold_a_tool_that_writes():
    allowed = fa.allowed_tools("plan", obsidian="obsidian-vault", launchers=LAUNCHERS)
    denied = fa.denied_tools("plan", obsidian="obsidian-vault")
    assert not names(allowed) & set(WRITING)
    assert {"vault_write", "vault_patch", "radar_mark_filed", "radar_filing_ask"} <= names(denied)
    assert "mcp__spyglass_filing__radar_filing_propose" in allowed
    assert "mcp__obsidian-vault__vault_read" in allowed


def test_a_filing_run_writes_only_through_the_note_tools_and_spyglass():
    allowed = fa.allowed_tools("file", obsidian="obsidian-vault", launchers=LAUNCHERS)
    assert "mcp__obsidian-vault__vault_write" in allowed
    assert "mcp__obsidian-vault__vault_patch" in allowed
    assert "mcp__spyglass_filing__radar_mark_filed" in allowed
    assert "mcp__spyglass_filing__radar_filing_propose" not in allowed
    assert not {"Write", "Edit", "MultiEdit"} & set(allowed)


def test_without_an_obsidian_server_no_obsidian_tool_is_listed():
    allowed = fa.allowed_tools("plan", obsidian=None, launchers=LAUNCHERS)
    assert not any("obsidian" in r for r in allowed)


def test_the_built_in_tools_are_a_fixed_short_list():
    assert fa.BUILT_IN == ("Read", "Glob", "Grep", "Skill", "ToolSearch", "Bash")


def test_find_plugin_reads_the_installed_list(tmp_path):
    root = tmp_path / "cache" / "vault-tool" / "1.0"
    root.mkdir(parents=True)
    listing = tmp_path / "installed_plugins.json"
    listing.write_text(json.dumps({"version": 2, "plugins": {
        "other@x": [{"installPath": str(tmp_path)}],
        "vault-tool@market": [{"scope": "user", "installPath": str(root)}]}}), encoding="utf-8")
    assert fa.find_plugin("vault-tool", listing) == root
    assert fa.find_plugin("missing", listing) is None
    assert fa.find_plugin("vault-tool", tmp_path / "absent.json") is None
    listing.write_text("not json", encoding="utf-8")
    assert fa.find_plugin("vault-tool", listing) is None


def test_vault_launchers_lists_only_the_forms_that_exist(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "vault-tool.sh").write_text("#!/bin/sh", encoding="utf-8")
    local = tmp_path / "local"
    assert fa.vault_launchers(plugin, "vault-tool", str(local)) == [
        f'bash "{(plugin / "scripts" / "vault-tool.sh").as_posix()}"']
    (local / "vault-tool").mkdir(parents=True)
    (local / "vault-tool" / "vault-tool").write_text("#!/bin/sh", encoding="utf-8")
    first = fa.vault_launchers(plugin, "vault-tool", str(local))[0]
    assert first == f'bash "{(local / "vault-tool" / "vault-tool").as_posix()}"'


def test_without_a_configured_tool_there_is_no_launcher_and_no_shell_entry(tmp_path, monkeypatch):
    monkeypatch.delenv("SPYGLASS_RADAR_FILING_TOOL")
    monkeypatch.delenv("SPYGLASS_RADAR_FILING_TOOL_COMMANDS")
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "vault-tool.sh").write_text("#!/bin/sh", encoding="utf-8")
    assert fa.vault_launchers(plugin, "vault-tool", None) == []
    # A launcher with no configured commands still gives no shell rule at all.
    for kind in fa.KINDS:
        assert not [r for r in fa.allowed_tools(kind, obsidian=None, launchers=LAUNCHERS)
                    if r.startswith("Bash")]


def test_the_tool_server_file_holds_no_secret(tmp_path):
    obsidian = {"type": "http", "url": "http://127.0.0.1:27123/mcp/",
                "headers": {"Authorization": "Bearer s3cret-value"}}
    config, extra_env = fa.mcp_config(7778, obsidian, "obsidian-vault")
    path = fa.write_mcp_config(tmp_path, config)
    text = path.read_text(encoding="utf-8")
    assert "s3cret" not in text
    servers = json.loads(text)["mcpServers"]
    assert servers["spyglass_filing"] == {"type": "http", "url": "http://127.0.0.1:7778/mcp/"}
    # The owner's server name is kept: the vault skills call its tools by that name.
    header = servers["obsidian-vault"]["headers"]["Authorization"]
    assert header.startswith("${") and extra_env[header[2:-1]] == "Bearer s3cret-value"


def test_the_tool_server_file_without_obsidian_names_spyglass_only(tmp_path):
    config, extra_env = fa.mcp_config(7778, None, "obsidian-vault")
    assert list(config["mcpServers"]) == ["spyglass_filing"] and extra_env == {}


def test_a_server_name_that_is_not_a_plain_token_is_refused():
    with pytest.raises(ValueError):
        fa.allowed_tools("plan", obsidian="bad name,Bash", launchers=LAUNCHERS)


def test_the_session_plugin_carries_this_versions_filing_skill(tmp_path):
    skills = tmp_path / "skills" / "spyglass-file"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: spyglass-file\n---\nBody", encoding="utf-8")
    root = fa.session_plugin(tmp_path / "data", tmp_path / "skills")
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == fa.PLUGIN
    assert (root / "skills" / "spyglass-file" / "SKILL.md").read_text(encoding="utf-8").endswith("Body")
    with pytest.raises(OSError):
        fa.session_plugin(tmp_path / "data", tmp_path / "nowhere")


def test_permission_settings_hold_the_allow_and_deny_lists(tmp_path):
    path = fa.write_permissions(tmp_path, ["Read"], ["Write"])
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Read"], "deny": ["Write"]}}
