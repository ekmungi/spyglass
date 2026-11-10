"""One-time relocation of operational state to the configured data dir.

Earlier builds stored the DB + settings under %LOCALAPPDATA%/Spyglass. When the
data dir moves to ~/.spyglass, move the existing files across once so the user keeps their
data. Idempotent, and never overwrites an existing file in the target.
"""

import shutil
from pathlib import Path

from platformdirs import user_data_dir

# Files carried over from the legacy home. The DB (with its WAL sidecars) is the one that
# matters; settings + the learned-preferences note are carried for continuity.
_MIGRATED_FILES = (
    "spyglass.db",
    "spyglass.db-wal",
    "spyglass.db-shm",
    "settings.json",
    "preferences.md",
)


def legacy_data_dir() -> Path:
    """The previous operational home (%LOCALAPPDATA%/Spyglass on Windows)."""
    return Path(user_data_dir("Spyglass", appauthor=False))


def migrate_data_dir(data_dir: Path, *, legacy_dir: Path | None = None) -> bool:
    """Move legacy operational files into data_dir once, if data_dir has no DB yet.

    Returns True if anything was moved. No-op (returns False) when the target already has a
    spyglass.db, the legacy dir resolves to the target, or the legacy dir has no DB. Never
    overwrites an existing file in data_dir. legacy_dir is injectable for tests.
    """
    legacy = legacy_dir if legacy_dir is not None else legacy_data_dir()
    try:
        same = legacy.resolve() == data_dir.resolve()
    except OSError:
        same = legacy == data_dir
    if same:
        return False
    if (data_dir / "spyglass.db").exists():
        return False
    if not (legacy / "spyglass.db").exists():
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    moved = False
    for name in _MIGRATED_FILES:
        src = legacy / name
        dst = data_dir / name
        if src.exists() and not dst.exists():
            shutil.move(str(src), str(dst))
            moved = True
    return moved
