"""The Claude Code connector that Windows setup adds, so Claude Code can use Spyglass's tools.

Setup adds a user-scope connector named "spyglass" through Claude Code's own command line, and
reads Claude Code's settings file only to see whether one already exists. A connector of that
name that points anywhere else is never replaced or removed: it is reported instead.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

# The name Claude Code lists the connector under; the vault's .mcp.json uses the same one.
SERVER_NAME = "spyglass"
# A command runner: (arguments, environment or None) -> (exit code, combined output).
Runner = Callable[[list[str], "dict | None"], tuple[int, str]]
# Host names that all mean this computer; "localhost" may resolve to ::1, so setup writes 127.0.0.1.
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def connector_url(port: int) -> str:
    """Where Spyglass serves its tools for Claude Code, as the vault's .mcp.json names it."""
    return f"http://127.0.0.1:{port}/mcp/"


def find_claude(home: Path, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The Claude Code command: PATH, then the native installer's and npm's usual folders."""
    found = which("claude")
    if found:
        return found
    candidates = [home / ".local" / "bin" / "claude.exe"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "claude.cmd")
    return next((str(path) for path in candidates if path.is_file()), None)


def _settings_file(home: Path) -> Path:
    """Claude Code's settings file: in CLAUDE_CONFIG_DIR when that is set, else in the home folder."""
    folder = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(folder) if folder else home) / ".claude.json"


def registered_url(home: Path) -> str | None:
    """The address of the user-scope "spyglass" connector, "" for one without an address, or
    None when there is none.

    A settings file that is missing or cannot be read counts as no connector: the add command
    then refuses a name that exists, so nothing is overwritten either way.
    """
    try:
        data = json.loads(_settings_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    if entry is None:
        return None
    url = entry.get("url") if isinstance(entry, dict) else None
    # An entry without an address (a command-line connector) is someone else's: "" never matches.
    return url if isinstance(url, str) else ""


def _is_ours(url: str, port: int) -> bool:
    """Whether `url` is this computer's Spyglass on `port` (any local host name, slash or not)."""
    parts = urlsplit(url.strip())
    return (parts.scheme == "http" and (parts.hostname or "") in _LOCAL_HOSTS
            and parts.port == port and parts.path.rstrip("/") == "/mcp")


def add_connector(claude: str | None, port: int, *, home: Path, run: Runner) -> str:
    """Add the connector when none exists. Returns added, present, foreign, no-claude or failed."""
    if claude is None:
        return "no-claude"
    existing = registered_url(home)
    if existing is not None:
        return "present" if _is_ours(existing, port) else "foreign"
    code, _output = run([claude, "mcp", "add", "--scope", "user", "--transport", "http",
                         SERVER_NAME, connector_url(port)], None)
    return "added" if code == 0 else "failed"


def remove_connector(claude: str | None, port: int, *, home: Path, run: Runner) -> str:
    """Remove the connector if it still points here. Returns removed, absent, foreign, no-claude
    or failed. The caller calls it only for a connector that setup itself added."""
    if claude is None:
        return "no-claude"
    existing = registered_url(home)
    if existing is None:
        return "absent"
    if not _is_ours(existing, port):
        return "foreign"
    code, _output = run([claude, "mcp", "remove", "--scope", "user", SERVER_NAME], None)
    return "removed" if code == 0 else "failed"
