"""Tests for the SQLite online backup helper (consistent snapshot + rotation)."""

from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.backup import backup_db, list_backups
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


def test_rotation_keeps_only_the_newest_n(tmp_path: Path) -> None:
    """Rotation retains the most recent `keep` backups and deletes older ones."""
    db = tmp_path / "spyglass.db"
    _seed_db(db)
    backups_dir = tmp_path / "b"
    timestamps = [datetime(2026, 6, 28, 0, 0, second) for second in range(5)]

    for ts in timestamps:
        backup_db(db, backups_dir=backups_dir, keep=3, timestamp=ts)

    remaining = list_backups(backups_dir)
    assert len(remaining) == 3
    # The three newest timestamps survive; the two oldest are gone.
    assert [p.name for p in remaining] == [
        "spyglass-20260628-000002.db",
        "spyglass-20260628-000003.db",
        "spyglass-20260628-000004.db",
    ]
