"""Register Spyglass with Claude: the vault's `.mcp.json` names the spyglass server.

A Claude desktop session opened in the vault finds MCP servers through `<vault>/.mcp.json`. The
README used to ask the user to copy `templates/vault-mcp.json` there by hand; now the service
makes sure the `spyglass` entry is present at startup, next to the skill sync. Only that entry is
added or its address updated: other servers and any extra fields the user added are kept, and a
file that cannot be read as the expected JSON is never rewritten. Failures are non-fatal.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SERVER_NAME = "spyglass"


def ensure_mcp_registration(vault_path: Path, port: int) -> bool:
    """Make sure `<vault>/.mcp.json` points Claude at this service's MCP endpoint.

    Returns True when the file was written, False when it was already right or was left alone.
    """
    path = vault_path / ".mcp.json"
    # 127.0.0.1, not localhost: the service binds IPv4 only, and on Windows "localhost" can resolve
    # to ::1 first. The trailing slash is the endpoint itself; "/mcp" answers with a redirect,
    # which an MCP client may not follow.
    url = f"http://127.0.0.1:{port}/mcp/"
    data: dict = {}
    if path.exists():
        try:
            # utf-8-sig: Notepad and Windows PowerShell 5 save JSON with a byte-order mark.
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            logger.warning("%s is not valid JSON; Spyglass left it unchanged", path)
            return False
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            logger.warning("%s has an unexpected shape; Spyglass left it unchanged", path)
            return False
    servers = data.setdefault("mcpServers", {})
    entry = servers.get(SERVER_NAME)
    if isinstance(entry, dict) and entry.get("url") == url:
        return False
    if isinstance(entry, dict) and "command" in entry:
        logger.info("%s runs spyglass as a command; Spyglass left it unchanged", path)
        return False
    updated = dict(entry) if isinstance(entry, dict) else {"type": "http"}
    updated["url"] = url
    servers[SERVER_NAME] = updated
    tmp = path.with_name(".mcp.json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.warning("Could not write %s; register Spyglass by hand", path, exc_info=True)
        tmp.unlink(missing_ok=True)
        return False
    return True
