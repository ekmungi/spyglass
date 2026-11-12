"""Tests for the SQLite online backup helper (consistent snapshot + rotation)."""

from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

import pytest

from spyglass_service import backup as backup_mod
from spyglass_service.backup import BackupSkipped, backup_db, list_backups
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item


def _seed_db(path: Path) -> None:
    """Create a database at path with one item so copies have verifiable content."""
    engine = create_db_engine(path)
    init_db(engine)
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="x1", title="T", url="https://x.test"))
        session.commit()
    engine.dispose()


def test_backup_creates_file_with_copied_data(tmp_path: Path) -> None:
    """A backup is a real, queryable copy of the live database, not an empty file."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)

    backup = backup_db(db, backups_dir=tmp_path / "backups")

    assert backup is not None
    assert backup.exists()
    engine = create_db_engine(backup)
    with Session(engine) as session:
        items = session.exec(select(Item)).all()
    engine.dispose()
    assert len(items) == 1
    assert items[0].external_id == "x1"


def test_backup_returns_none_when_database_missing(tmp_path: Path) -> None:
    """With no database to copy, the helper is a no-op rather than an error."""
    assert backup_db(tmp_path / "absent.db", backups_dir=tmp_path / "backups") is None


def test_backup_filename_uses_timestamp(tmp_path: Path) -> None:
    """The backup is named spyglass-YYYYMMDD-HHMMSS.db for chronological sorting."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)

    backup = backup_db(db, backups_dir=tmp_path / "b", timestamp=datetime(2026, 6, 28, 0, 16, 3))

    assert backup is not None
    assert backup.name == "spyglass-20260628-001603.db"


def test_backup_collision_appends_suffix(tmp_path: Path) -> None:
    """Two backups in the same second produce two distinct files (no overwrite)."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    ts = datetime(2026, 6, 28, 0, 16, 3)
    backups_dir = tmp_path / "b"

    first = backup_db(db, backups_dir=backups_dir, timestamp=ts)
    second = backup_db(db, backups_dir=backups_dir, timestamp=ts)

    assert first is not None and second is not None
    assert first != second
    assert len(list_backups(backups_dir)) == 2


def test_list_backups_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    """Listing a not-yet-created backups dir is empty, not an error."""
    assert list_backups(tmp_path / "never-made") == []


def test_backup_second_collision_increments_suffix(tmp_path: Path) -> None:
    """A third backup in the same second walks past -1 to a free -2 name."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    ts = datetime(2026, 6, 28, 0, 16, 3)
    backups_dir = tmp_path / "b"

    backup_db(db, backups_dir=backups_dir, timestamp=ts)
    backup_db(db, backups_dir=backups_dir, timestamp=ts)
    third = backup_db(db, backups_dir=backups_dir, timestamp=ts)

    assert third is not None
    assert third.name == "spyglass-20260628-001603-2.db"


def test_negative_keep_retains_all_backups(tmp_path: Path) -> None:
    """A misconfigured negative keep is a safety no-op: nothing is deleted."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"

    for second in range(3):
        backup_db(
            db, backups_dir=backups_dir, keep=-1, timestamp=datetime(2026, 6, 28, 0, 0, second)
        )

    assert len(list_backups(backups_dir)) == 3


def test_same_day_rotation_keeps_only_the_newest_two(tmp_path: Path) -> None:
    """Snapshots from one day never fill more than two slots, so older days can survive."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"

    for second in range(5):
        backup_db(db, backups_dir=backups_dir, keep=7,
                  timestamp=datetime(2026, 6, 28, 0, 0, second))

    assert [p.name for p in list_backups(backups_dir)] == [
        "spyglass-20260628-000003.db",
        "spyglass-20260628-000004.db",
    ]


def _seed_days(backups_dir: Path) -> None:
    """Three snapshots a day (08:00, 12:00, 20:00) for the ten days before 28 June 2026."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    for day in range(18, 28):
        for hour in (8, 12, 20):
            (backups_dir / f"spyglass-202606{day}-{hour:02d}0000.db").write_bytes(b"x")


def test_rotation_keeps_the_newest_two_and_one_per_previous_five_days(tmp_path: Path) -> None:
    """Older days keep their last snapshot for five days; everything else is removed."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    _seed_days(backups_dir)

    backup_db(db, backups_dir=backups_dir, keep=7, timestamp=datetime(2026, 6, 28, 10, 0, 0))

    assert [p.name for p in list_backups(backups_dir)] == [
        "spyglass-20260623-200000.db",
        "spyglass-20260624-200000.db",
        "spyglass-20260625-200000.db",
        "spyglass-20260626-200000.db",
        "spyglass-20260627-200000.db",
        "spyglass-20260628-100000.db",
    ]


def test_rotation_keeps_the_two_newest_even_when_both_are_from_today(tmp_path: Path) -> None:
    """Two snapshots from today are both kept, plus the last one of each earlier day."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    _seed_days(backups_dir)

    backup_db(db, backups_dir=backups_dir, keep=7, timestamp=datetime(2026, 6, 28, 9, 0, 0))
    backup_db(db, backups_dir=backups_dir, keep=7, timestamp=datetime(2026, 6, 28, 10, 0, 0))

    names = [p.name for p in list_backups(backups_dir)]
    assert names[-2:] == ["spyglass-20260628-090000.db", "spyglass-20260628-100000.db"]
    assert len(names) == 7
    assert "spyglass-20260627-200000.db" in names and "spyglass-20260623-200000.db" in names


def test_keep_bounds_the_total(tmp_path: Path) -> None:
    """When the rule would keep more than `keep`, the oldest are dropped first."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    _seed_days(backups_dir)

    backup_db(db, backups_dir=backups_dir, keep=3, timestamp=datetime(2026, 6, 28, 10, 0, 0))

    assert [p.name for p in list_backups(backups_dir)] == [
        "spyglass-20260626-200000.db",
        "spyglass-20260627-200000.db",
        "spyglass-20260628-100000.db",
    ]


def test_default_keep_covers_the_rule() -> None:
    """The default bound is the rule's own maximum: two newest plus five earlier days."""
    assert backup_mod.DEFAULT_KEEP == 7


def test_low_disk_skips_the_snapshot_with_a_plain_reason(tmp_path: Path, monkeypatch) -> None:
    """Less than twice the newest snapshot's size free means no snapshot, and no failure."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    backups_dir.mkdir()
    (backups_dir / "spyglass-20260627-200000.db").write_bytes(b"x" * 100)
    monkeypatch.setattr(backup_mod, "_free_bytes", lambda _folder: 199)

    with pytest.raises(BackupSkipped) as caught:
        backup_db(db, backups_dir=backups_dir, timestamp=datetime(2026, 6, 28, 10, 0, 0))

    assert "disk" in str(caught.value).lower()
    assert [p.name for p in list_backups(backups_dir)] == ["spyglass-20260627-200000.db"]


def test_enough_disk_takes_the_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Exactly twice the newest snapshot's size free is enough."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    backups_dir.mkdir()
    (backups_dir / "spyglass-20260627-200000.db").write_bytes(b"x" * 100)
    monkeypatch.setattr(backup_mod, "_free_bytes", lambda _folder: 200)

    assert backup_db(db, backups_dir=backups_dir, timestamp=datetime(2026, 6, 28, 10, 0, 0))


def test_first_snapshot_needs_no_disk_check(tmp_path: Path, monkeypatch) -> None:
    """With no earlier snapshot there is nothing to size against, so the check is not made."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    monkeypatch.setattr(backup_mod, "_free_bytes", lambda _folder: 0)

    assert backup_db(db, backups_dir=tmp_path / "b") is not None
