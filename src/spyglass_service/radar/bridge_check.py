"""Check that Claude Code, opened in the vault, is connected to THIS running Spyglass.

A session opened in the vault finds Spyglass's tools through the vault's `.mcp.json`. The service
writes its own `spyglass` entry there when it starts (see `mcp_register`), so two Spyglass
services that share one vault take turns owning the entry, and a vault last used by another
copy points at that copy. A session sent from this copy would then call tools that belong to a
different database and find nothing. This module reads the file and compares the address in it
with the address of the running service, so the hand-off can refuse with a plain reason instead.

Nothing is written here. A file that is missing, unreadable or malformed never raises.
"""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from spyglass_service.mcp_register import SERVER_NAME

logger = logging.getLogger(__name__)

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
NOT_CONNECTED = ("Claude Code in this vault is not connected to Spyglass yet. Restart Spyglass "
                 "with this vault folder set, then try again.")
MALFORMED = ("The .mcp.json file in this vault cannot be read, so Spyglass cannot tell whether "
             "Claude Code is connected to it. Fix or delete that file, restart Spyglass, then "
             "try again.")


def service_address(settings) -> str:
    """The address of this running service, as a session on the same machine reaches it."""
    # 127.0.0.1, not localhost: it is the address `mcp_register` writes into the vault.
    return f"http://127.0.0.1:{settings.port}"


def _servers(vault: Path) -> dict | None:
    """The `mcpServers` object of the vault's `.mcp.json`; {} when absent; None when unusable."""
    path = vault / ".mcp.json"
    if not path.exists():
        return {}
    try:
        # utf-8-sig: Notepad and Windows PowerShell 5 save JSON with a byte-order mark.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        logger.warning("%s cannot be read as JSON", path)
        return None
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers", {})
    return servers if isinstance(servers, dict) else None


def _is_spyglass_entry(name: str, entry: dict) -> bool:
    """True for the entry the service writes, or a local `/mcp/` entry named like one."""
    if name == SERVER_NAME:
        return True
    url = entry.get("url")
    if not name.lower().startswith(SERVER_NAME) or not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.hostname in LOCAL_HOSTS and parts.path.rstrip("/").endswith("/mcp")


def _where(url: str) -> tuple[bool, int | None, str]:
    """(is a local address, its port, how to name it) for an entry's address."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False, None, url
    local = parts.hostname in LOCAL_HOSTS
    return local, port, f"port {port}" if local and port else url


def _not_connected(settings) -> str:
    """The reason when no entry exists, worded for whether the service adds it by itself."""
    if getattr(settings, "register_mcp", True):
        return NOT_CONNECTED
    return ("Claude Code in this vault is not connected to Spyglass yet, and Spyglass is set not "
            "to add itself to the vault's .mcp.json. Add a spyglass entry with the address "
            f"{service_address(settings)}/mcp/ to that file, then try again.")


def tool_server_problem(settings) -> str | None:
    """Why a session opened in the vault would not reach this Spyglass, or None when it would.

    No problem when any Spyglass entry points at this service's port on a local address. An
    entry that runs Spyglass as a command (no address) cannot be compared and is left alone.
    """
    vault = getattr(settings, "vault_path", None)
    if vault is None:
        return None
    servers = _servers(Path(vault))
    if servers is None:
        return MALFORMED
    found = {name: entry for name, entry in servers.items()
             if isinstance(entry, dict) and _is_spyglass_entry(str(name), entry)}
    if not found:
        return _not_connected(settings)
    others: list[str] = []
    for name, entry in sorted(found.items(), key=lambda pair: pair[0] != SERVER_NAME):
        url = entry.get("url")
        if not isinstance(url, str):
            return None
        local, port, label = _where(url)
        if local and port == settings.port:
            return None
        others.append(label)
    return (f"Claude Code in this vault is connected to another Spyglass ({others[0]}), not this "
            f"one (port {settings.port}), so it would not find the items from this one.")
