"""The desktop settings file and the check that a data folder suits this Spyglass.

The installer writes `desktop.json` (where the data lives, the vault, the port). Before the
service opens a data folder, `check_data_dir` refuses one that holds an older Spyglass (no
redesign tables) or one a newer Spyglass has used (`spyglass-data.json` names a newer version).
The check only reads: it opens the database read-only and creates nothing.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import platformdirs

from spyglass_service.radar.models import RadarDoc

DB_NAME = "spyglass.db"
VERSION_FILE = "spyglass-data.json"
DEFAULT_PORT = 7777


@dataclass(frozen=True)
class DesktopConfig:
    """What the installer decided: the data folder, an optional vault, and the port."""

    data_dir: Path
    vault_path: Path | None = None
    port: int = DEFAULT_PORT


class ConfigError(ValueError):
    """`desktop.json` exists but cannot be used."""


class FolderVerdict(IntEnum):
    """Result of the data folder check; the values double as process exit codes."""

    OK = 0
    OLDER = 3
    NEWER = 4
    MISSING = 5


def config_path() -> Path:
    """Where `desktop.json` lives: the per-user config folder, under "Spyglass"."""
    return Path(platformdirs.user_config_dir("Spyglass", appauthor=False)) / "desktop.json"


def load_config(path: Path | None = None) -> DesktopConfig | None:
    """Read the settings file. Returns None when it is missing; raises ConfigError otherwise
    when the JSON is bad or `data_dir` is absent or not text."""
    target = path or config_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"Cannot read {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{target} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{target} must hold a JSON object")
    data_dir = data.get("data_dir")
    if not isinstance(data_dir, str) or not data_dir:
        raise ConfigError(f"{target} needs a text value for data_dir")
    vault = data.get("vault_path")
    if vault is not None and not isinstance(vault, str):
        raise ConfigError(f"{target}: vault_path must be text or null")
    port = data.get("port", DEFAULT_PORT)
    # bool is an int subclass; a JSON true must not pass as port 1.
    if not isinstance(port, int) or isinstance(port, bool):
        raise ConfigError(f"{target}: port must be a number")
    return DesktopConfig(data_dir=Path(data_dir), vault_path=Path(vault) if vault else None, port=port)


def save_config(config: DesktopConfig, path: Path | None = None) -> None:
    """Write the settings file as UTF-8 JSON, creating its folder. Non-ASCII stays readable."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "data_dir": str(config.data_dir),
        "vault_path": str(config.vault_path) if config.vault_path else None,
        "port": config.port,
    }
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def _version_tuple(version: str) -> tuple[int, ...] | None:
    """'0.41.0' -> (0, 41, 0); None when it is not dotted integers."""
    try:
        return tuple(int(part) for part in version.strip().split("."))
    except (ValueError, AttributeError):
        return None


def _recorded_version(folder: Path) -> str | None:
    """The version that last wrote this folder, or None if unrecorded or unreadable."""
    try:
        data = json.loads((folder / VERSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    written_by = data.get("written_by") if isinstance(data, dict) else None
    return written_by if isinstance(written_by, str) else None


def _has_redesign_tables(db: Path) -> bool:
    """True unless the database is readable and lacks the radar table. A file that cannot be
    opened as a database is not called old: the service's own integrity check deals with it."""
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return True
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (RadarDoc.__tablename__,),
        ).fetchone()
    except sqlite3.Error:
        return True
    finally:
        conn.close()
    return row is not None


def check_data_dir(path: Path, own_version: str, *, must_exist: bool = False) -> tuple[FolderVerdict, str]:
    """Decide whether `path` suits Spyglass `own_version`. Returns (verdict, message to show).

    The installer passes must_exist=False because it creates the folder; the launcher passes
    True because a missing folder then means the install was damaged. Nothing is written.
    """
    if not path.exists():
        if must_exist:
            return FolderVerdict.MISSING, f"The Spyglass data folder {path} is missing."
        return FolderVerdict.OK, ""
    recorded = _recorded_version(path)
    recorded_tuple = _version_tuple(recorded) if recorded else None
    own_tuple = _version_tuple(own_version)
    if recorded_tuple and own_tuple and recorded_tuple > own_tuple:
        return FolderVerdict.NEWER, (
            f"The data folder {path} was last used by Spyglass {recorded}, which is newer than "
            f"this Spyglass {own_version}. Install the newer version, or choose another folder."
        )
    db = path / DB_NAME
    if db.exists() and not _has_redesign_tables(db):
        return FolderVerdict.OLDER, (
            f"The data folder {path} holds data from an older Spyglass that this version "
            "cannot open. Choose a new, empty folder."
        )
    return FolderVerdict.OK, ""


def record_data_version(data_dir: Path, version: str) -> None:
    """Note which Spyglass last wrote `data_dir`, so an older one can refuse it later."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / VERSION_FILE).write_text(json.dumps({"written_by": version}), encoding="utf-8")
