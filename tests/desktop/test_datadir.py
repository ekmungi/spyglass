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


def test_check_leaves_a_wal_database_and_its_folder_untouched(tmp_path: Path) -> None:
    """The service runs its database in WAL mode; a plain read-only open would add -wal and -shm
    files to the folder, so the check must not leave any trace there."""
    db = _make_db(tmp_path, "card")
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    conn.close()
    names_before = sorted(p.name for p in tmp_path.iterdir())
    bytes_before = db.read_bytes()
    assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OLDER
    assert sorted(p.name for p in tmp_path.iterdir()) == names_before
    assert db.read_bytes() == bytes_before


def test_table_still_in_the_wal_file_counts_as_present(tmp_path: Path) -> None:
    """After a crash the newest tables can sit only in the -wal file; the check must see them
    (else it would refuse the user's own data) and still leave the folder as it found it."""
    db = _make_db(tmp_path, "card")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute(f'CREATE TABLE "{RadarDoc.__tablename__}" (id INTEGER PRIMARY KEY)')
    conn.commit()
    try:
        assert (tmp_path / "spyglass.db-wal").stat().st_size > 0
        names_before = sorted(p.name for p in tmp_path.iterdir())
        assert check_data_dir(tmp_path, "0.41.0")[0] is FolderVerdict.OK
        assert sorted(p.name for p in tmp_path.iterdir()) == names_before
    finally:
        conn.close()


def test_check_reads_a_folder_whose_name_looks_percent_encoded(tmp_path: Path) -> None:
    """A folder named like '100%41 x' must be opened literally, not as '100A x'."""
    folder = tmp_path / "100%41 x"
    _make_db(folder, "card")
    assert check_data_dir(folder, "0.41.0")[0] is FolderVerdict.OLDER


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


@pytest.mark.parametrize(("recorded", "own", "kept"), [
    ("0.42.0", "0.41.0", "0.42.0"),   # an older developer start keeps the newer-data guard
    ("0.40.1", "0.41.0", "0.41.0"),   # a newer Spyglass records itself
    ("not-a-version", "0.41.0", "0.41.0"),
])
def test_record_data_version_keeps_the_newer_of_the_two(
        tmp_path: Path, recorded: str, own: str, kept: str) -> None:
    """The developer entry does not run the folder check, so it can start on a folder a newer
    Spyglass used. It must not erase that version, or the newer app's guard is lost."""
    record_data_version(tmp_path, recorded)
    record_data_version(tmp_path, own)
    written = json.loads((tmp_path / "spyglass-data.json").read_text(encoding="utf-8"))
    assert written == {"written_by": kept}


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


@pytest.mark.parametrize("body", ["{}", '{"data_dir": null, "vault_path": null, "port": 7790}',
                                  '{"data_dir": ""}'])
def test_a_settings_file_naming_no_data_folder_means_first_start(tmp_path: Path, body: str) -> None:
    """Setup writes data_dir null; the app then starts on the default folder and asks."""
    path = tmp_path / "desktop.json"
    path.write_text(body, encoding="utf-8")
    loaded = load_config(path)
    assert loaded is not None and loaded.first_start is True
    assert loaded.data_dir == tmp_path / "data"


def test_a_settings_file_naming_a_data_folder_is_no_first_start(tmp_path: Path) -> None:
    path = tmp_path / "desktop.json"
    save_config(DesktopConfig(data_dir=tmp_path / "d"), path)
    assert load_config(path).first_start is False


@pytest.mark.parametrize("body", ["{", '{"data_dir": 5}', '[1]', '{"data_dir": "x", "port": "7"}'])
def test_load_config_rejects_bad_json_and_missing_keys(tmp_path: Path, body: str) -> None:
    path = tmp_path / "desktop.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_load_config_rejects_a_port_no_service_can_listen_on(tmp_path: Path, port: int) -> None:
    """Port 0 would bind a random port while the launcher opens http://127.0.0.1:0/."""
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"data_dir": "x", "port": port}), encoding="utf-8")
    with pytest.raises(ConfigError, match="65535"):
        load_config(path)


@pytest.mark.parametrize("port", [1, 65535])
def test_load_config_accepts_both_ends_of_the_port_range(tmp_path: Path, port: int) -> None:
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"data_dir": "x", "port": port}), encoding="utf-8")
    loaded = load_config(path)
    assert loaded is not None and loaded.port == port


@pytest.mark.parametrize("encoding", ["utf-16", "cp1252"])
def test_load_config_asks_for_utf8_when_the_file_is_in_another_encoding(
        tmp_path: Path, encoding: str) -> None:
    """Windows PowerShell 5.1 writes UTF-16 with `>` or Out-File and ANSI with Set-Content. Such a
    file must give the usual settings message, which says how to save it, not a crash."""
    path = tmp_path / "desktop.json"
    path.write_text('{"data_dir": "C:\\\\Users\\\\Zoë\\\\data"}', encoding=encoding)
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(path)


def test_load_config_reads_utf8_with_a_byte_order_mark(tmp_path: Path) -> None:
    """Windows PowerShell 5.1's `Out-File -Encoding UTF8` writes UTF-8 with a byte order mark."""
    path = tmp_path / "desktop.json"
    path.write_text('{"data_dir": "C:\\\\Zoë", "port": 7790}', encoding="utf-8-sig")
    assert load_config(path) == DesktopConfig(data_dir=Path("C:\\Zoë"), port=7790)


def test_config_path_names_desktop_json(monkeypatch) -> None:
    monkeypatch.delenv("SPYGLASS_DESKTOP_CONFIG", raising=False)
    assert config_path().name == "desktop.json"
    assert config_path().parent.name == "Spyglass"


def test_config_path_honours_the_test_override(tmp_path: Path, monkeypatch) -> None:
    """Manual and installer test runs point the launcher at a scratch desktop.json."""
    scratch = tmp_path / "scratch" / "desktop.json"
    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(scratch))
    assert config_path() == scratch
    save_config(DesktopConfig(data_dir=tmp_path / "data", port=7790))
    assert load_config() == DesktopConfig(data_dir=tmp_path / "data", port=7790)


def test_service_start_records_its_version(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with TestClient(create_app(settings)):
        pass
    written = json.loads((tmp_path / "data" / "spyglass-data.json").read_text(encoding="utf-8"))
    assert written["written_by"] == __version__
