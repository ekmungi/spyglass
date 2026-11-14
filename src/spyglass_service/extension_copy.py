"""A per-install copy of the browser extension that carries this install's address and key.

The service keeps the copy in its data folder, so the user loads a folder that always matches the
running Spyglass, and the extension can read the address and key from a file in that folder
instead of asking the user to paste them from Settings.

The config file holds the address, the key and a stamp. The stamp is a fingerprint of the address
and key only: it changes when either one changes and never on a mere refresh of the copy. The
extension adopts the key when the stamp is new to it, so a key the user typed by hand survives an
upgrade and is replaced only when the key or the address really changed.
"""

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# The copy's folder name inside the data folder, and the config file inside the copy.
COPY_DIR = "browser-extension"
CONFIG_FILE = "spyglass-config.json"
# Top-level folders of the source that hold development tooling, not the extension itself.
_EXCLUDED = frozenset({"tests", "tools"})


def config_stamp(address: str, key: str) -> str:
    """The first 16 hex characters of the SHA-256 of the address and key, joined by a newline."""
    return hashlib.sha256(f"{address}\n{key}".encode()).hexdigest()[:16]


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` through a temporary file, so a reader never sees half a file.

    The file holds the key, so it is created readable by the owner only where the system allows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)


def write_extension_config(data_dir: Path | str, address: str, key: str) -> None:
    """Write the copy's config: the address, the key and the stamp that follows from both."""
    config = {"address": address, "key": key, "stamp": config_stamp(address, key)}
    _atomic_write(Path(data_dir) / COPY_DIR / CONFIG_FILE, json.dumps(config, indent=2) + "\n")


def _manifest_version(folder: Path) -> str | None:
    """The `version` in the folder's manifest.json, or None when it is missing or unreadable."""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) else None


def _skip_development_folders(source: Path):
    """A `shutil.copytree` ignore function that drops the top-level tests and tools folders."""

    def ignore(directory: str, names: list[str]) -> set[str]:
        return _EXCLUDED.intersection(names) if Path(directory) == source else set()

    return ignore


def sync_extension_copy(source: Path, data_dir: Path | str, address: str, key: str) -> Path:
    """Make the data folder's copy of the extension current and return its folder.

    The copy is rebuilt from `source` (without the tests and tools folders) when it is missing or
    its manifest version differs from the source's; otherwise it is left as it is. The config is
    always rewritten, which is harmless because its stamp depends only on the address and key.
    """
    folder = Path(data_dir) / COPY_DIR
    source_version = _manifest_version(source)
    if source_version is None:
        logger.warning("no readable extension manifest in %s; the copy was not refreshed", source)
        if _manifest_version(folder) is None:
            return folder  # nothing to configure: do not leave a folder holding only a config
    elif _manifest_version(folder) != source_version:
        if folder.exists():
            shutil.rmtree(folder)
        shutil.copytree(source, folder, ignore=_skip_development_folders(source))
        logger.info("copied the browser extension %s into %s", source_version, folder)
    write_extension_config(data_dir, address, key)
    return folder
