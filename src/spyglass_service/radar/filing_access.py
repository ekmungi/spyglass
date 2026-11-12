"""What a background filing session may use: its tools, its tool servers and the vault skills.

All lists are built here, in one place, and tested. A session is started with `--restricted`, so
none of the owner's settings files are read (no allow rules, no other plugins, no hooks of
theirs), and with `--strict-mcp-config`, so it sees only the two tool servers Spyglass names:
this service's own tools under the name `spyglass_filing`, and the owner's Obsidian server under
its own name (the vault skills call its tools by that name). The vault skills come from the one
plugin that holds them (`--plugin-dir`).

Two kinds of run:
- "plan" writes nothing: reading tools, the vault tool's read-only look-up commands, and the
  Spyglass tools that read the queue, propose a row and report.
- "file" also writes, but only through the Obsidian server's create and patch tools and the
  Spyglass tools that record what was filed, ask the one question and mark an answer applied.
Never, in any run: deleting, moving, renaming, copying or appending notes, Obsidian commands,
file writes or edits, web tools, sub-agents or a general shell. The shell is allowed only as the
vault tool's look-up commands, by exact prefix, and every other command is refused without
asking (`--permission-mode dontAsk`).

The Obsidian server's key is never written to a file: the server entry names an environment
variable for each header, and the runner passes the values to the child process only.
"""

import json
import logging
import re
from pathlib import Path

from spyglass_service.radar.filing_config import tool_commands, tool_name

logger = logging.getLogger(__name__)

SERVER = "spyglass_filing"
# The name of the one-skill plugin that carries Spyglass's own filing instructions.
PLUGIN = "spyglass-filing"
KINDS = ("plan", "file")
BUILT_IN = ("Read", "Glob", "Grep", "Skill", "ToolSearch", "Bash")
SPYGLASS_TOOLS = {
    "plan": ("radar_filing_queue", "radar_get_item", "radar_filing_propose", "radar_filing_report"),
    "file": ("radar_filing_queue", "radar_get_item", "radar_mark_filed", "radar_filing_ask",
             "radar_filing_applied", "radar_filing_report"),
}
SPYGLASS_WRITERS = ("radar_mark_filed", "radar_filing_ask", "radar_filing_applied")
OBSIDIAN_READ = ("vault_read", "vault_get_document_map", "vault_list", "search_query",
                 "search_simple")
OBSIDIAN_WRITE = ("vault_write", "vault_patch")
OBSIDIAN_NEVER = ("vault_delete", "vault_move", "vault_copy", "vault_append", "command_execute",
                  "command_list", "open_file", "active_file_get_path", "vault_get_upload_url",
                  "vault_get_download_url", "events_get_listener_url", "tag_list")
DENIED_BUILT_IN = ("Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
                   "Agent", "PowerShell")
# Claude Code lets read-only shell commands run without a rule inside the session's folders (the
# vault and the plugin folder; outside them they are refused). They are denied by name, so the
# shell stays the vault tool's look-ups only; Read, Glob and Grep do the same reading.
SHELL_READERS = ("ls", "cat", "head", "tail", "find", "grep", "rg", "cd", "pwd", "echo", "type",
                 "wc", "sort", "uniq", "which", "where", "dir", "more", "less", "tree", "stat",
                 "file", "du", "df", "cut", "awk", "sed", "xargs", "env", "printenv", "set")
HEADER_ENV = "SPYGLASS_FILING_HEADER_{}"
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _check_name(name: str) -> str:
    """`name` when it is a plain server name, else ValueError (it becomes part of a rule)."""
    if not _NAME.fullmatch(name):
        raise ValueError("The Obsidian server name must be letters, digits, '.', '_' or '-'.")
    return name


def _mcp(server: str, tools: tuple[str, ...]) -> list[str]:
    """Rule names for a server's tools."""
    return [f"mcp__{server}__{tool}" for tool in tools]


def vault_command_rules(launchers: list[str], commands: tuple[str, ...] | None = None) -> list[str]:
    """`Bash(<launcher> <command>:*)` for every launcher form and allowed look-up command.

    `commands` defaults to the owner's configured list (`filing_config.tool_commands`); with none
    configured the result is empty, so the allow list holds no shell entry at all.
    """
    allowed = tool_commands() if commands is None else commands
    return [f"Bash({launcher} {command}:*)" for launcher in launchers for command in allowed]


def allowed_tools(kind: str, *, obsidian: str | None, launchers: list[str],
                  commands: tuple[str, ...] | None = None) -> list[str]:
    """Everything a run of `kind` may call; anything else is refused without asking."""
    if kind not in KINDS:
        raise ValueError("unknown run kind")
    rules = ["Read", "Glob", "Grep", "Skill", "ToolSearch",
             *vault_command_rules(launchers, commands),
             *_mcp(SERVER, SPYGLASS_TOOLS[kind])]
    if obsidian:
        server = _check_name(obsidian)
        rules += _mcp(server, OBSIDIAN_READ)
        if kind == "file":
            rules += _mcp(server, OBSIDIAN_WRITE)
    return rules


def denied_tools(kind: str, *, obsidian: str | None) -> list[str]:
    """Tools refused outright in a run of `kind`, whatever else would allow them."""
    if kind not in KINDS:
        raise ValueError("unknown run kind")
    rules = [*DENIED_BUILT_IN, *(f"Bash({name}:*)" for name in SHELL_READERS)]
    if kind == "plan":
        rules += _mcp(SERVER, SPYGLASS_WRITERS)
    else:
        rules += _mcp(SERVER, ("radar_filing_propose",))
    if obsidian:
        server = _check_name(obsidian)
        rules += _mcp(server, OBSIDIAN_NEVER)
        if kind == "plan":
            rules += _mcp(server, OBSIDIAN_WRITE)
    return rules


def find_plugin(name: str, plugins_json: Path) -> Path | None:
    """The install folder of the Claude Code plugin `name` (any marketplace), or None."""
    try:
        data = json.loads(plugins_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plugins = data.get("plugins", data) if isinstance(data, dict) else {}
    for key, installs in (plugins.items() if isinstance(plugins, dict) else []):
        if not isinstance(key, str) or key.split("@", 1)[0] != name:
            continue
        for install in installs if isinstance(installs, list) else []:
            path = install.get("installPath") if isinstance(install, dict) else None
            if isinstance(path, str) and Path(path).is_dir():
                return Path(path)
    return None


def vault_launchers(plugin_root: Path, plugin_name: str, local_app_data: str | None,
                    tool: str | None = None) -> list[str]:
    """The ways the vault skills run their command-line tool, as exact command prefixes.

    `tool` is the launcher's file name (default: `filing_config.tool_name`, empty when not
    configured, which gives no launcher). The fixed launcher the plugin's start-up writes under
    the local application-data folder comes first, then the plugin's own script. Only forms whose
    file exists are listed; paths use forward slashes, written out in full (a `$VARIABLE` in a
    command never matches a rule).
    """
    name = tool_name() if tool is None else tool
    if not name:
        return []
    forms: list[Path] = []
    if local_app_data:
        forms.append(Path(local_app_data) / plugin_name / name)
    forms.append(plugin_root / "scripts" / f"{name}.sh")
    return [f'bash "{p.as_posix()}"' for p in forms if p.is_file()]


def mcp_config(port: int, obsidian: dict | None, obsidian_name: str) -> tuple[dict, dict]:
    """The session's tool servers and the environment values their headers refer to.

    `obsidian` is the owner's server entry (type, url, headers) or None. Each header value is
    replaced by `${SPYGLASS_FILING_HEADER_<n>}`, and the real value goes into the returned
    environment additions, so the file written from this holds no secret.
    """
    servers: dict = {SERVER: {"type": "http", "url": f"http://127.0.0.1:{int(port)}/mcp/"}}
    extra_env: dict[str, str] = {}
    if obsidian:
        entry = {k: v for k, v in obsidian.items() if k in ("type", "url")}
        headers = obsidian.get("headers") if isinstance(obsidian.get("headers"), dict) else {}
        if headers:
            entry["headers"] = {}
            for index, (key, value) in enumerate(headers.items()):
                variable = HEADER_ENV.format(index)
                extra_env[variable] = str(value)
                entry["headers"][key] = "${" + variable + "}"
        servers[_check_name(obsidian_name)] = entry
    return {"mcpServers": servers}, extra_env


def write_mcp_config(folder: Path, config: dict) -> Path:
    """Write the tool-server file for a run into `folder`; returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "filing-mcp.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def session_plugin(folder: Path, skills_dir: Path) -> Path:
    """A one-skill plugin holding Spyglass's own `spyglass-file` skill, for `--plugin-dir`.

    The session then has the filing instructions of this Spyglass version, whatever the vault's
    own skills folder holds, and nothing is written into the vault for it. Raises OSError when
    the skill file cannot be read.
    """
    text = (skills_dir / "spyglass-file" / "SKILL.md").read_text(encoding="utf-8")
    root = folder / "session-plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "spyglass-file").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": PLUGIN, "version": "1.0.0",
        "description": "Spyglass's filing instructions for a background run."}), encoding="utf-8")
    (root / "skills" / "spyglass-file" / "SKILL.md").write_text(text, encoding="utf-8")
    return root


def write_permissions(folder: Path, allow: list[str], deny: list[str]) -> Path:
    """Write the run's allow and deny lists as a settings file for `--settings`; returns its path.

    A file rather than arguments: the rules hold quotes, which a Windows batch-file launcher of
    `claude` would hand to its command shell.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "filing-permissions.json"
    path.write_text(json.dumps({"permissions": {"allow": allow, "deny": deny}}, indent=2),
                    encoding="utf-8")
    return path
