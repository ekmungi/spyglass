"""Consistent SQLite backups: snapshot the live DB and rotate old copies.

Spyglass has no other backup; a hung writer once corrupted the operational DB
with nothing to restore from. This writes a defragmented, transactionally
consistent copy on startup, after each refresh and every night.

Retention keeps the newest two snapshots plus the newest snapshot of each of the previous five
calendar days (local time), so several snapshots taken within one day cannot push every older day
out. A snapshot is skipped, with a plain reason, when the disk is nearly full.
"""

import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

# Glob used for both writing and rotation; the timestamp keeps names sortable.
_BACKUP_GLOB = "spyglass-*.db"
_NAME_FORMAT = "spyglass-%Y%m%d-%H%M%S.db"
# Upper bound on the snapshots kept in total (setting `backup_keep`). The retention rule itself keeps
# at most seven (the newest two plus one for each of the previous five days), so this is its maximum.
DEFAULT_KEEP = 7
# The newest snapshots always kept, however many were taken today.
NEWEST_KEPT = 2
# How many calendar days before the current one keep their newest snapshot.
PREVIOUS_DAYS_KEPT = 5
# A snapshot needs this many times the newest snapshot's size free on the disk, or it is skipped.
FREE_SPACE_FACTOR = 2
# The date inside a snapshot name (spyglass-YYYYMMDD-HHMMSS[-n].db).
_NAME_DATE = re.compile(r"^spyglass-(\d{8})-\d{6}")


class BackupSkipped(Exception):
    """A snapshot was deliberately not taken; the message is a plain sentence for the run log."""


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
    to the database; keep is the upper bound on how many copies survive rotation (a negative value
    keeps them all). Raises BackupSkipped, without writing anything, when the disk has less than
    twice the newest existing snapshot's size free.
    """
    if not db_path.exists():
        return None

    target_dir = backups_dir if backups_dir is not None else db_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    _require_space(target_dir)
    moment = timestamp or datetime.now()
    target = _unique_target(target_dir, moment)

    # A short-lived read connection is enough; VACUUM INTO reads through the WAL.
    connection = sqlite3.connect(db_path)
    try:
        # The target path is interpolated (VACUUM INTO takes no bind params); the
        # filename is timestamp-derived and quote-escaped, so this is injection-safe.
        escaped = str(target).replace("'", "''")
        connection.execute(f"VACUUM INTO '{escaped}'")
    finally:
        connection.close()

    _rotate(target_dir, keep, moment.date())
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


def _free_bytes(folder: Path) -> int:
    """Free bytes on the disk holding `folder` (replaced in tests)."""
    return shutil.disk_usage(folder).free


def _require_space(folder: Path) -> None:
    """Raise BackupSkipped unless the disk has room for another snapshot as large as the newest."""
    existing = list_backups(folder)
    if not existing:
        return
    newest = existing[-1].stat().st_size
    free = _free_bytes(folder)
    if free < FREE_SPACE_FACTOR * newest:
        raise BackupSkipped(
            f"Backup skipped: the disk has {free // 1_048_576} MB free and a backup needs about "
            f"{FREE_SPACE_FACTOR * newest // 1_048_576} MB.")


def _snapshot_day(path: Path) -> date | None:
    """The local calendar day a snapshot was taken, read from its name; None when unreadable."""
    found = _NAME_DATE.match(path.name)
    if found is None:
        return None
    try:
        return datetime.strptime(found.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _to_keep(backups: list[Path], today: date) -> set[Path]:
    """The snapshots the retention rule keeps: the newest two, plus the newest of each earlier day.

    `backups` is sorted oldest first. The earlier days are the `PREVIOUS_DAYS_KEPT` calendar days
    before `today`.
    """
    kept = set(backups[-NEWEST_KEPT:])
    wanted = {today - timedelta(days=n) for n in range(1, PREVIOUS_DAYS_KEPT + 1)}
    newest_of_day: dict[date, Path] = {}
    for path in backups:  # later names overwrite earlier ones, leaving each day's newest
        day = _snapshot_day(path)
        if day in wanted:
            newest_of_day[day] = path
    return kept | set(newest_of_day.values())


def _rotate(backups_dir: Path, keep: int, today: date) -> None:
    """Delete the snapshots the rule does not keep, then the oldest ones beyond the bound `keep`."""
    backups = list_backups(backups_dir)
    if keep < 0:
        return
    kept = sorted(_to_keep(backups, today), key=lambda p: p.name)
    survivors = set(kept[max(0, len(kept) - keep):])
    for stale in backups:
        if stale not in survivors:
            stale.unlink()
