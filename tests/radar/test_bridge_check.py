"""Tests for the check that the vault's Claude Code is connected to THIS Spyglass.

Only temporary folders are used; no real vault, service or network is touched.
"""

import json

import pytest

from spyglass_service.config import Settings
from spyglass_service.radar.bridge_check import (
    MALFORMED,
    NOT_CONNECTED,
    service_address,
    tool_server_problem,
)


def make_settings(tmp_path, *, port: int = 7778, register: bool = True) -> Settings:
    """Settings for a service on `port` with `tmp_path` as its vault."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path, port=port,
                    register_mcp=register)


def write_servers(tmp_path, servers: dict, *, bom: bool = False) -> None:
    """Write `<vault>/.mcp.json` with the given server entries."""
    text = json.dumps({"mcpServers": servers})
    (tmp_path / ".mcp.json").write_text(text, encoding="utf-8-sig" if bom else "utf-8")


def entry(port: int, host: str = "127.0.0.1") -> dict:
    """One HTTP tool-server entry for a local service."""
    return {"type": "http", "url": f"http://{host}:{port}/mcp/"}


def test_the_service_address_uses_its_own_port(tmp_path):
    assert service_address(make_settings(tmp_path, port=7778)) == "http://127.0.0.1:7778"


def test_a_matching_entry_is_no_problem(tmp_path):
    write_servers(tmp_path, {"spyglass": entry(7778)})
    assert tool_server_problem(make_settings(tmp_path)) is None


def test_a_byte_order_mark_and_other_servers_are_tolerated(tmp_path):
    write_servers(tmp_path, {"obsidian": entry(27123), "spyglass": entry(7778, "localhost")},
                  bom=True)
    assert tool_server_problem(make_settings(tmp_path)) is None


def test_a_missing_file_means_not_connected_yet(tmp_path):
    assert tool_server_problem(make_settings(tmp_path)) == NOT_CONNECTED
    assert "Restart Spyglass" in NOT_CONNECTED


def test_a_file_without_a_spyglass_entry_means_not_connected_yet(tmp_path):
    # An unrelated server that happens to use the same port and path is not a Spyglass entry.
    write_servers(tmp_path, {"obsidian": entry(7778)})
    assert tool_server_problem(make_settings(tmp_path)) == NOT_CONNECTED


def test_not_connected_says_what_to_do_when_spyglass_does_not_register_itself(tmp_path):
    reason = tool_server_problem(make_settings(tmp_path, register=False))
    assert reason is not None and "Restart Spyglass" not in reason
    assert "http://127.0.0.1:7778/mcp/" in reason and ".mcp.json" in reason


def test_an_entry_for_another_port_names_both_ports(tmp_path):
    write_servers(tmp_path, {"spyglass": entry(7777)})
    reason = tool_server_problem(make_settings(tmp_path, port=7778))
    assert reason == ("Claude Code in this vault is connected to another Spyglass (port 7777), "
                      "not this one (port 7778), so it would not find the items from this one.")


def test_an_entry_on_another_machine_is_named_by_its_address(tmp_path):
    write_servers(tmp_path, {"spyglass": {"type": "http", "url": "https://tools.example/mcp/"}})
    reason = tool_server_problem(make_settings(tmp_path))
    assert reason is not None and "tools.example" in reason and "port 7778" in reason


def test_a_second_spyglass_entry_for_another_port_is_ignored_when_one_matches(tmp_path):
    write_servers(tmp_path, {"spyglass": entry(7778), "spyglass-old": entry(7777)})
    assert tool_server_problem(make_settings(tmp_path)) is None


def test_an_entry_whose_name_starts_with_spyglass_counts(tmp_path):
    write_servers(tmp_path, {"spyglass-test": entry(7778)})
    assert tool_server_problem(make_settings(tmp_path)) is None
    write_servers(tmp_path, {"spyglass-test": entry(7777)})
    assert "port 7777" in (tool_server_problem(make_settings(tmp_path)) or "")


def test_a_spyglass_entry_run_as_a_command_cannot_be_compared_and_is_left_alone(tmp_path):
    write_servers(tmp_path, {"spyglass": {"command": "spyglass-mcp", "args": []}})
    assert tool_server_problem(make_settings(tmp_path)) is None


@pytest.mark.parametrize("text", ["{not json", "[]", '{"mcpServers": []}', '{"mcpServers": 3}',
                                  "", "null"])
def test_a_malformed_file_gets_its_own_reason(tmp_path, text):
    (tmp_path / ".mcp.json").write_text(text, encoding="utf-8")
    assert tool_server_problem(make_settings(tmp_path)) == MALFORMED


def test_an_unreadable_file_gets_the_malformed_reason(tmp_path):
    (tmp_path / ".mcp.json").mkdir()  # reading a folder as a file fails with an OS error
    assert tool_server_problem(make_settings(tmp_path)) == MALFORMED


def test_a_file_with_no_servers_key_means_not_connected_yet(tmp_path):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    assert tool_server_problem(make_settings(tmp_path)) == NOT_CONNECTED


def test_a_server_entry_that_is_not_an_object_is_ignored(tmp_path):
    write_servers(tmp_path, {"spyglass": "oops"})
    assert tool_server_problem(make_settings(tmp_path)) == NOT_CONNECTED


def test_no_vault_is_no_problem_here(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=None)
    assert tool_server_problem(settings) is None
