"""Tests for the desktop settings file and the data folder check."""

import json
import sqlite3
from pathlib import Path

import pytest

from spyglass_service import __version__
from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.desktop.datadir import (
    ConfigError,
    DesktopConfig,
    FolderVerdict,
    check_data_dir,
    config_path,
    load_config,
    record_data_version,
    save_config,
)
from spyglass_service.radar.models import RadarDoc


def _make_db(folder: Path, table: str) -> Path:
    """Create spyglass.db in `folder` holding one table with the given name."""
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "spyglass.db"
    conn = sqlite3.connect(db)
    conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()
    return db


def test_empty_or_absent_folder_is_ok(tmp_path: Path) -> None:
    assert check_data_dir(tmp_path / "x", "0.41.0")[0] is FolderVerdict.OK
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK


def test_database_without_redesign_tables_is_older(tmp_path: Path) -> None:
    _make_db(tmp_path, "card")
    verdict, message = check_data_dir(tmp_path, "0.41.0")
    assert verdict is FolderVerdict.OLDER
    assert message


def test_database_with_redesign_tables_is_ok(tmp_path: Path) -> None:
    _make_db(tmp_path, RadarDoc.__tablename__)
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK


def test_check_changes_nothing(tmp_path: Path) -> None:
    db = _make_db(tmp_path, "card")
    before_bytes, before_mtime = db.read_bytes(), db.stat().st_mtime_ns
    check_data_dir(tmp_path, "0.41.0")
    assert db.read_bytes() == before_bytes
    assert db.stat().st_mtime_ns == before_mtime
    assert sorted(p.name for p in tmp_path.iterdir()) == ["spyglass.db"]


def test_folder_used_by_a_newer_version_is_refused(tmp_path: Path) -> None:
    record_data_version(tmp_path, "0.42.0")
    verdict, message = check_data_dir(tmp_path, "0.41.0")
    assert verdict is FolderVerdict.NEWER and "0.42.0" in message


def test_version_compare_is_numeric_not_textual(tmp_path: Path) -> None:
    record_data_version(tmp_path, "0.9.0")
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK
    record_data_version(tmp_path, "0.100.0")
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.NEWER


def test_same_or_older_recorded_version_passes(tmp_path: Path) -> None:
    record_data_version(tmp_path, "0.41.0")
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK


def test_folder_without_version_file_passes_the_newer_rule(tmp_path: Path) -> None:
    _make_db(tmp_path, RadarDoc.__tablename__)
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK


def test_unparsable_version_file_is_not_newer(tmp_path: Path) -> None:
    (tmp_path / "spyglass-data.json").write_text("{not json", encoding="utf-8")
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK
    (tmp_path / "spyglass-data.json").write_text('{"written_by": "banana"}', encoding="utf-8")
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK


def test_missing_folder_is_refused_for_an_existing_install(tmp_path: Path) -> None:
    assert check_data_dir(tmp_path / "gone", "0.41.0", must_exist=True)[0] is FolderVerdict.MISSING


def test_record_data_version_writes_the_version(tmp_path: Path) -> None:
    record_data_version(tmp_path / "new", "0.41.0")
    written = json.loads((tmp_path / "new" / "spyglass-data.json").read_text(encoding="utf-8"))
    assert written == {"written_by": "0.41.0"}


def test_config_round_trips_spaces_and_non_ascii(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "desktop.json"
    config = DesktopConfig(
        data_dir=Path("C:/Users/Ann Smith/Spyglaß data"),
        vault_path=Path("C:/Vault Ünï"),
        port=7790,
    )
    save_config(config, path)
    assert "Spyglaß" in path.read_text(encoding="utf-8")
    assert load_config(path) == config


def test_config_defaults_and_missing_file(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.json") is None
    path = tmp_path / "desktop.json"
    save_config(DesktopConfig(data_dir=tmp_path / "d"), path)
    loaded = load_config(path)
    assert loaded is not None and loaded.vault_path is None and loaded.port == 7777


@pytest.mark.parametrize("body", ["{", "{}", '{"data_dir": 5}', '[1]', '{"data_dir": "x", "port": "7"}'])
def test_load_config_rejects_bad_json_and_missing_keys(tmp_path: Path, body: str) -> None:
    path = tmp_path / "desktop.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_config_path_names_desktop_json() -> None:
    assert config_path().name == "desktop.json"
    assert config_path().parent.name == "Spyglass"


def test_service_start_records_its_version(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with TestClient(create_app(settings)):
        pass
    written = json.loads((tmp_path / "data" / "spyglass-data.json").read_text(encoding="utf-8"))
    assert written["written_by"] == __version__
