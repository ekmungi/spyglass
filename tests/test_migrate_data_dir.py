"""Tests for the one-time data-dir relocation to ~/.spyglass."""

from pathlib import Path

from spyglass_service.migrate_data_dir import migrate_data_dir


def _seed_legacy(legacy: Path, *, db: bool = True, extras: bool = True) -> None:
    """Create a fake legacy data dir with a DB (and optional settings/prefs)."""
    legacy.mkdir(parents=True, exist_ok=True)
    if db:
        (legacy / "spyglass.db").write_text("dbdata", encoding="utf-8")
    if extras:
        (legacy / "settings.json").write_text("{}", encoding="utf-8")
        (legacy / "preferences.md").write_text("prefs", encoding="utf-8")


def test_migrates_db_and_extras_when_target_empty(tmp_path) -> None:
    """A legacy DB + settings move into an empty target once."""
    legacy = tmp_path / "legacy"
    data_dir = tmp_path / "new"
    _seed_legacy(legacy)

    moved = migrate_data_dir(data_dir, legacy_dir=legacy)

    assert moved is True
    assert (data_dir / "spyglass.db").read_text(encoding="utf-8") == "dbdata"
    assert (data_dir / "settings.json").exists()
    assert (data_dir / "preferences.md").exists()
    assert not (legacy / "spyglass.db").exists()  # moved, not copied


def test_no_op_when_target_already_has_db(tmp_path) -> None:
    """An existing target DB is never overwritten; the legacy DB is left untouched."""
    legacy = tmp_path / "legacy"
    data_dir = tmp_path / "new"
    _seed_legacy(legacy)
    data_dir.mkdir()
    (data_dir / "spyglass.db").write_text("keep-me", encoding="utf-8")

    moved = migrate_data_dir(data_dir, legacy_dir=legacy)

    assert moved is False
    assert (data_dir / "spyglass.db").read_text(encoding="utf-8") == "keep-me"
    assert (legacy / "spyglass.db").exists()


def test_no_op_when_no_legacy_db(tmp_path) -> None:
    """Nothing to migrate when the legacy dir has no DB."""
    legacy = tmp_path / "legacy"
    data_dir = tmp_path / "new"
    _seed_legacy(legacy, db=False, extras=False)

    assert migrate_data_dir(data_dir, legacy_dir=legacy) is False
    assert not (data_dir / "spyglass.db").exists()


def test_no_op_when_legacy_is_same_as_target(tmp_path) -> None:
    """When the legacy dir resolves to the target, do nothing (and never delete it)."""
    data_dir = tmp_path / "same"
    _seed_legacy(data_dir)

    assert migrate_data_dir(data_dir, legacy_dir=data_dir) is False
    assert (data_dir / "spyglass.db").exists()


def test_is_idempotent(tmp_path) -> None:
    """A second run after a successful migration is a no-op."""
    legacy = tmp_path / "legacy"
    data_dir = tmp_path / "new"
    _seed_legacy(legacy)

    assert migrate_data_dir(data_dir, legacy_dir=legacy) is True
    assert migrate_data_dir(data_dir, legacy_dir=legacy) is False
