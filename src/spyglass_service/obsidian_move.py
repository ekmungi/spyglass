"""Moving a note through the user's Obsidian MCP server, so links and the note's comments follow it.

A filing run has no Obsidian tool. It names a folder, and Spyglass makes the one move itself with
the server settings Claude Code uses (`find_obsidian_server`): an HTTP address and a login header
that may name an environment variable, as in `Bearer ${OBSIDIAN_API_KEY}`.
"""

import asyncio
import os
import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlsplit

from fastmcp import Client
from fastmcp.client.transports import (
    ClientTransport,
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from fastmcp.exceptions import ToolError

from spyglass_service.claude_jobs import ObsidianServerMissing, find_obsidian_server
from spyglass_service.config import Settings

# Long enough for Obsidian to rename a note and rewrite the links that point to it.
MOVE_TIMEOUT_S = 30.0
# ${NAME} and ${NAME:-default}, the references Claude Code fills in from the environment.
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
# Words of a login header that are not secret: the names of the login schemes.
_SCHEMES = frozenset({"bearer", "basic", "token"})
# Shorter words are too common to hide without garbling a message, and too short to be a key.
_MIN_SECRET = 6
HIDDEN = "[hidden]"


class ObsidianMoveError(Exception):
    """The move did not happen; the message says why in plain words."""


def expand_env(value: str, env: Mapping[str, str] | None = None) -> str:
    """Fill in ${NAME} and ${NAME:-default} from the environment, as Claude Code does in a server
    setting. A name that is not set and has no default raises ObsidianMoveError naming it."""
    source = os.environ if env is None else env

    def fill(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in source and (source[name] != "" or default is None):
            return source[name]
        if default is not None:
            return default
        raise ObsidianMoveError(
            f"The settings of your Obsidian server use ${{{name}}}, but Spyglass's environment "
            f"has no {name}. Set it for the program that starts Spyglass, then restart Spyglass.")

    return _REFERENCE.sub(fill, value)


def transport_for(server: dict, env: Mapping[str, str] | None = None,
                  name: str = "obsidian-vault") -> ClientTransport:
    """The client transport for a server entry of a Claude config file: an address (http, or sse)
    or a command to run. Raises ObsidianMoveError for anything else."""
    url, command = server.get("url"), server.get("command")
    kind = str(server.get("type") or ("http" if url else "stdio")).lower()
    if kind in ("http", "sse") and isinstance(url, str):
        headers = {key: expand_env(str(value), env)
                   for key, value in (server.get("headers") or {}).items()}
        transport = SSETransport if kind == "sse" else StreamableHttpTransport
        return transport(expand_env(url, env), headers=headers or None)
    if kind == "stdio" and isinstance(command, str):
        args = [expand_env(str(arg), env) for arg in server.get("args") or []]
        child_env = {key: expand_env(str(value), env)
                     for key, value in (server.get("env") or {}).items()}
        return StdioTransport(expand_env(command, env), args, env=child_env or None)
    raise ObsidianMoveError(
        f"Spyglass cannot use the settings of your Obsidian server \"{name}\": they need an http "
        "address or a command.")


def _expand_quietly(value: str, env: Mapping[str, str]) -> str:
    """expand_env, keeping the text as it is when a variable is missing."""
    try:
        return expand_env(value, env)
    except ObsidianMoveError:
        return value


def secrets_of(server: dict, env: Mapping[str, str] | None = None) -> list[str]:
    """Values from a server's settings that no error text may repeat, longest first: header and
    environment values, the address's query, and every ${NAME} filled in, each whole and word by
    word. An error goes back to the run, which an article can steer, so a key must not be in it."""
    source = os.environ if env is None else env
    values = [str(v) for v in (server.get("headers") or {}).values()]
    values += [str(v) for v in (server.get("env") or {}).values()]
    url = str(server.get("url") or "")
    settings_text = [*values, url, str(server.get("command") or ""),
                     *(str(arg) for arg in server.get("args") or [])]
    filled = [source.get(m.group(1), "") for text in settings_text
              for m in _REFERENCE.finditer(text)]
    values = [_expand_quietly(value, source) for value in values] + filled
    query = urlsplit(_expand_quietly(url, source)).query
    values += [query] + [value for _name, value in parse_qsl(query)]
    words = {word for value in values for word in (value.strip(), *value.split())
             if len(word) >= _MIN_SECRET and word.lower() not in _SCHEMES}
    return sorted(words, key=len, reverse=True)


def hide(text: str, secrets: list[str]) -> str:
    """The text with every secret replaced by [hidden]."""
    for secret in secrets:
        text = text.replace(secret, HIDDEN)
    return text


def _leaves(exc: BaseException) -> list[BaseException]:
    """The errors inside an exception group, or the error itself."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


def _words(exc: BaseException) -> str:
    """One line saying what went wrong, from the innermost errors."""
    texts = dict.fromkeys(str(leaf) or type(leaf).__name__ for leaf in _leaves(exc))
    return "; ".join(texts)


async def move_note(settings: Settings, source: str, destination: str, *,
                    timeout: float = MOVE_TIMEOUT_S) -> None:
    """Ask the user's Obsidian server to move a note. Both paths are relative to the vault; a
    destination ending in "/" keeps the note's name. Nothing is ever overwritten. Raises
    ObsidianMoveError, with the reason in plain words, when the move did not happen."""
    name = settings.obsidian_mcp_server
    try:
        server = find_obsidian_server(settings)
    except ObsidianServerMissing as exc:
        raise ObsidianMoveError(str(exc)) from exc
    transport = transport_for(server, name=name)
    secrets = secrets_of(server)
    arguments = {"path": source, "destination": destination, "allowOverwrite": False}
    try:
        # The client's own time limits sit a little above ours, so ours fires first and says so.
        async with asyncio.timeout(timeout):
            async with Client(transport, timeout=timeout + 5, init_timeout=timeout + 5) as client:
                await client.call_tool("vault_move", arguments)
    except ObsidianMoveError:
        raise
    except TimeoutError as exc:
        # Not "the note was not moved": Obsidian may have moved it and answered late, so the
        # caller looks at the vault to find out.
        raise ObsidianMoveError(f"Obsidian did not answer within {int(timeout)} seconds.") from exc
    except ToolError as exc:
        raise ObsidianMoveError(hide(f"Obsidian refused the move: {exc}", secrets)) from exc
    except Exception as exc:  # noqa: BLE001 -- anything on the way to Obsidian ends the same way
        raise ObsidianMoveError(hide(
            f"Spyglass could not reach your Obsidian MCP server \"{name}\" ({_words(exc)}). "
            "Check that Obsidian is open and that the server's address and key are right.",
            secrets)) from exc
