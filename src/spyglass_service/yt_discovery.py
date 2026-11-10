"""Locate the yt-transcribe CLI.

Video full-text shells out to the external `yt-transcribe` binary, but the service
must find it -- and `~/.local/bin` is often not on the service's PATH. This resolves the path in a
sensible order so the reliable transcript path works without manual config in the common case:

  1. the YouTube Transcribe Obsidian plugin's own configured `executablePath` (reuse it);
  2. PATH (`shutil.which`);
  3. known `uv tool install` locations (~/.local/bin, the uv tools Scripts dir).
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

# The YouTube Transcribe Obsidian plugin's id -- its config lives at
# <vault>/.obsidian/plugins/<id>/data.json with an `executablePath`.
_PLUGIN_ID = "youtube-transcribe"


def _from_obsidian_plugin(vault_path: Path | None) -> str | None:
    """The path the YouTube Transcribe plugin already has configured, if it names an existing file.

    A bare "yt-transcribe" (a PATH reference, the plugin's default) is intentionally ignored here so
    resolution falls through to the PATH tier; only a concrete, existing file path is reused.
    """
    if vault_path is None:
        return None
    data = vault_path / ".obsidian" / "plugins" / _PLUGIN_ID / "data.json"
    try:
        cfg = json.loads(data.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    exe = cfg.get("executablePath")
    if isinstance(exe, str) and exe.strip() and Path(exe).is_file():
        return exe
    return None


def _known_locations(home: Path) -> list[Path]:
    """Common yt-transcribe install locations (uv tool install), most-specific first."""
    return [
        home / ".local" / "bin" / "yt-transcribe.exe",
        home / ".local" / "bin" / "yt-transcribe",
        home / "AppData" / "Roaming" / "uv" / "tools" / "yt-transcribe" / "Scripts"
        / "yt-transcribe.exe",
    ]


def discover_yt_transcribe(
    vault_path: Path | None,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] | None = None,
) -> str | None:
    """Resolve the yt-transcribe CLI path, or None if it cannot be found.

    Order: the YouTube Transcribe plugin's configured path -> PATH -> known install locations.

    Args:
        vault_path: The Obsidian vault root (for the plugin-config tier); None to skip it.
        home: Home directory for the known-locations tier (defaults to Path.home()); injectable.
        which: PATH lookup (defaults to shutil.which); injectable for tests.

    Returns:
        A command/path string for the CLI, or None when no binary is found (caller then relies on
        the youtube-transcript-api fallback).
    """
    plugin = _from_obsidian_plugin(vault_path)
    if plugin:
        return plugin
    found = (which or shutil.which)("yt-transcribe")
    if found:
        return found
    for path in _known_locations(home or Path.home()):
        if path.is_file():
            return str(path)
    return None
