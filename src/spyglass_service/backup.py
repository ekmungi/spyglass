"""Consistent SQLite backups: snapshot the live DB and rotate old copies.

Spyglass has no other backup; a hung writer once corrupted the operational DB
with nothing to restore from. This writes a defragmented, transactionally
consistent copy on startup and after each refresh, keeping the last N.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# Glob used for both writing and rotation; the timestamp keeps names sortable.
_BACKUP_GLOB = "spyglass-*.db"
_NAME_FORMAT = "spyglass-%Y%m%d-%H%M%S.db"
# Default number of backups to retain; older copies are deleted on each run.
DEFAULT_KEEP = 5


def list_backups(backups_dir: Path) -> list[Path]:
    """Return existing backup files sorted oldest-first by their timestamped name.

    Names embed YYYYMMDD-HHMMSS, so a plain string sort is chronological. A
    missing directory yields an empty list rather than an error.
    """
    if not backups_dir.is_dir():
        return []
    return sorted(backups_dir.glob(_BACKUP_GLOB), key=lambda p: p.name)


def backup_db(
    db_path: Path,
    *,
    backups_dir: Path | None = None,
    keep: int = DEFAULT_KEEP,
    timestamp: datetime | None = None,
) -> Path | None:
    """Write a consistent copy of db_path into backups_dir and rotate old copies.

    Uses SQLite's `VACUUM INTO`, which produces a defragmented, transactionally
    consistent single-file snapshot even while WAL mode is active -- no manual
    checkpoint needed. Returns the new backup path, or None if db_path does not
    exist (nothing to back up). backups_dir defaults to a `backups/` folder next
    to the database; keep bounds how many copies survive rotation.
    """
    if not db_path.exists():
        return None

    target_dir = backups_dir if backups_dir is not None else db_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_target(target_dir, timestamp or datetime.now())

    # A short-lived read connection is enough; VACUUM INTO reads through the WAL.
    connection = sqlite3.connect(db_path)
    try:
        # The target path is interpolated (VACUUM INTO takes no bind params); the
        # filename is timestamp-derived and quote-escaped, so this is injection-safe.
        escaped = str(target).replace("'", "''")
        connection.execute(f"VACUUM INTO '{escaped}'")
    finally:
        connection.close()

    _rotate(target_dir, keep)
    return target


def _unique_target(backups_dir: Path, timestamp: datetime) -> Path:
    """Pick a not-yet-existing backup path for timestamp.

    VACUUM INTO refuses to overwrite, so on a same-second collision we append a
    numeric suffix (still sorts within the second) until the name is free.
    """
    base = backups_dir / timestamp.strftime(_NAME_FORMAT)
    if not base.exists():
        return base
    stem = base.stem  # e.g. "spyglass-20260628-001603"
    suffix = 1
    while True:
        candidate = backups_dir / f"{stem}-{suffix}.db"
        if not candidate.exists():
            return candidate
        suffix += 1


def _rotate(backups_dir: Path, keep: int) -> None:
    """Delete all but the newest `keep` backups in backups_dir."""
    backups = list_backups(backups_dir)
    if keep < 0:
        return
    for stale in backups[: max(0, len(backups) - keep)]:
        stale.unlink()
