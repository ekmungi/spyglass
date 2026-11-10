"""Tests for registering Spyglass in the vault's .mcp.json."""

import json
import logging
from pathlib import Path

from spyglass_service.mcp_register import ensure_mcp_registration


def read(vault: Path) -> dict:
    return json.loads((vault / ".mcp.json").read_text(encoding="utf-8"))


def test_creates_the_file_when_missing(tmp_path: Path) -> None:
    assert ensure_mcp_registration(tmp_path, 7777) is True
    assert read(tmp_path) == {
        "mcpServers": {"spyglass": {"type": "http", "url": "http://127.0.0.1:7777/mcp/"}}
    }


def test_keeps_other_servers(tmp_path: Path) -> None:
    other = {"mcpServers": {"obsidian": {"command": "npx", "args": ["obsidian-mcp"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(other), encoding="utf-8")
    assert ensure_mcp_registration(tmp_path, 7777) is True
    servers = read(tmp_path)["mcpServers"]
    assert servers["obsidian"] == other["mcpServers"]["obsidian"]
    assert servers["spyglass"]["url"] == "http://127.0.0.1:7777/mcp/"


def test_updates_only_the_address_of_an_existing_entry(tmp_path: Path) -> None:
    mine = {"mcpServers": {"spyglass": {"type": "http", "url": "http://localhost:1/mcp",
                                        "headers": {"X-Note": "kept"}}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(mine), encoding="utf-8")
    assert ensure_mcp_registration(tmp_path, 7777) is True
    entry = read(tmp_path)["mcpServers"]["spyglass"]
    assert entry == {"type": "http", "url": "http://127.0.0.1:7777/mcp/",
                     "headers": {"X-Note": "kept"}}


def test_leaves_a_correct_file_untouched(tmp_path: Path) -> None:
    ensure_mcp_registration(tmp_path, 7777)
    before = (tmp_path / ".mcp.json").read_bytes()
    assert ensure_mcp_registration(tmp_path, 7777) is False
    assert (tmp_path / ".mcp.json").read_bytes() == before


def test_never_rewrites_a_file_it_cannot_read(tmp_path: Path, caplog) -> None:
    (tmp_path / ".mcp.json").write_text("{ not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert ensure_mcp_registration(tmp_path, 7777) is False
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == "{ not json"
    assert "not valid JSON" in caplog.text


def test_never_rewrites_a_file_of_another_shape(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text('{"mcpServers": []}', encoding="utf-8")
    assert ensure_mcp_registration(tmp_path, 7777) is False
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == '{"mcpServers": []}'


def test_reads_a_file_saved_with_a_byte_order_mark(tmp_path: Path) -> None:
    other = {"mcpServers": {"obsidian": {"command": "npx"}}}
    (tmp_path / ".mcp.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(other).encode())
    assert ensure_mcp_registration(tmp_path, 7777) is True
    assert set(read(tmp_path)["mcpServers"]) == {"obsidian", "spyglass"}


def test_leaves_a_command_entry_alone(tmp_path: Path) -> None:
    mine = {"mcpServers": {"spyglass": {"command": "uvx", "args": ["spyglass-mcp"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(mine), encoding="utf-8")
    assert ensure_mcp_registration(tmp_path, 7777) is False
    assert read(tmp_path) == mine


def test_rewrites_the_old_address(tmp_path: Path) -> None:
    """Entries written before 0.31.0 used localhost and /mcp, which redirects; fix them in place."""
    old = {"mcpServers": {"spyglass": {"type": "http", "url": "http://localhost:7777/mcp"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(old), encoding="utf-8")
    assert ensure_mcp_registration(tmp_path, 7777) is True
    assert read(tmp_path)["mcpServers"]["spyglass"]["url"] == "http://127.0.0.1:7777/mcp/"
