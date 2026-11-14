"""The per-install copy of the browser extension that carries this install's address and key.

The service keeps the copy in its data folder so the extension can adopt the key by itself. The
stamp in the copy's config must change only when the address or the key changes, never on a copy
refresh: a key the user typed by hand is only replaced when the config really changed.
"""

import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.extension_copy import (
    CONFIG_FILE,
    COPY_DIR,
    config_stamp,
    sync_extension_copy,
    write_extension_config,
)

ADDRESS = "http://127.0.0.1:7777"
KEY = "a" * 32


def make_source(root: Path, version: str = "1.0.0") -> Path:
    """A small fake extension source folder, with the folders the copy must leave out."""
    source = root / "source"
    (source / "icons").mkdir(parents=True)
    (source / "tests" / "e2e").mkdir(parents=True)
    (source / "tools").mkdir()
    (source / "manifest.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (source / "background.js").write_text("// background", encoding="utf-8")
    (source / "icons" / "icon.png").write_bytes(b"png")
    (source / "tests" / "e2e" / "run.py").write_text("# test", encoding="utf-8")
    (source / "tools" / "make.py").write_text("# tool", encoding="utf-8")
    return source


def read_config(data_dir: Path) -> dict:
    """The config the copy holds, as a dict."""
    return json.loads((data_dir / COPY_DIR / CONFIG_FILE).read_text(encoding="utf-8"))


def test_copy_excludes_tests_and_tools(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    data = tmp_path / "data"
    folder = sync_extension_copy(source, data, ADDRESS, KEY)
    assert folder == data / COPY_DIR
    assert (folder / "manifest.json").is_file()
    assert (folder / "background.js").is_file()
    assert (folder / "icons" / "icon.png").is_file()
    assert not (folder / "tests").exists()
    assert not (folder / "tools").exists()


def test_a_nested_folder_named_tests_is_kept(tmp_path: Path) -> None:
    """Only the top-level tests and tools folders are development leftovers."""
    source = make_source(tmp_path)
    (source / "icons" / "tests").mkdir()
    (source / "icons" / "tests" / "keep.txt").write_text("x", encoding="utf-8")
    folder = sync_extension_copy(source, tmp_path / "data", ADDRESS, KEY)
    assert (folder / "icons" / "tests" / "keep.txt").is_file()


def test_copy_is_refreshed_when_the_manifest_version_changes(tmp_path: Path) -> None:
    source = make_source(tmp_path, "1.0.0")
    data = tmp_path / "data"
    folder = sync_extension_copy(source, data, ADDRESS, KEY)
    (folder / "stale.js").write_text("// left over", encoding="utf-8")

    # Same version: the copy is left as it is.
    (source / "background.js").write_text("// changed but same version", encoding="utf-8")
    sync_extension_copy(source, data, ADDRESS, KEY)
    assert (folder / "background.js").read_text(encoding="utf-8") == "// background"
    assert (folder / "stale.js").exists()

    # New version: the copy is rebuilt from the source.
    (source / "manifest.json").write_text(json.dumps({"version": "1.1.0"}), encoding="utf-8")
    sync_extension_copy(source, data, ADDRESS, KEY)
    assert (folder / "background.js").read_text(encoding="utf-8") == "// changed but same version"
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["version"] == "1.1.0"
    assert not (folder / "stale.js").exists()
    assert read_config(data)["key"] == KEY


def test_a_missing_copy_is_made_even_when_nothing_else_changed(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    data = tmp_path / "data"
    sync_extension_copy(source, data, ADDRESS, KEY)
    (data / COPY_DIR / "manifest.json").unlink()
    sync_extension_copy(source, data, ADDRESS, KEY)
    assert (data / COPY_DIR / "manifest.json").is_file()


def test_config_holds_address_key_and_a_stable_stamp(tmp_path: Path) -> None:
    write_extension_config(tmp_path, ADDRESS, KEY)
    first = read_config(tmp_path)
    assert first["address"] == ADDRESS and first["key"] == KEY
    assert first["stamp"] == config_stamp(ADDRESS, KEY)
    write_extension_config(tmp_path, ADDRESS, KEY)
    assert read_config(tmp_path)["stamp"] == first["stamp"]


def test_the_stamp_is_sixteen_hex_characters_and_follows_address_and_key() -> None:
    stamp = config_stamp(ADDRESS, KEY)
    assert len(stamp) == 16 and int(stamp, 16) >= 0
    assert stamp != config_stamp(ADDRESS, "b" * 32)
    assert stamp != config_stamp("http://127.0.0.1:7790", KEY)


def test_a_refresh_keeps_the_stamp(tmp_path: Path) -> None:
    source = make_source(tmp_path, "1.0.0")
    data = tmp_path / "data"
    sync_extension_copy(source, data, ADDRESS, KEY)
    before = read_config(data)["stamp"]
    (source / "manifest.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    sync_extension_copy(source, data, ADDRESS, KEY)
    assert read_config(data)["stamp"] == before


def test_a_failed_refresh_keeps_the_previous_copy_whole_and_is_repaired_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_source(tmp_path, "1.0.0")
    data = tmp_path / "data"
    folder = sync_extension_copy(source, data, ADDRESS, KEY)
    # A new version with more files, so the copy has several files to fail in the middle of.
    (source / "manifest.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    for name in ("a.js", "b.js", "c.js", "d.js"):
        (source / name).write_text(f"// {name}", encoding="utf-8")

    real_copy = shutil.copy2
    copied: list[str] = []

    def fail_after_two(src, dst, **kwargs):
        if len(copied) >= 2:
            raise OSError("disk full")
        copied.append(str(src))
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", fail_after_two)
    with pytest.raises(OSError):
        sync_extension_copy(source, data, ADDRESS, KEY)

    # The previous copy is intact and complete, with its config; no temporary folder is left.
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
    assert (folder / "background.js").is_file() and (folder / "icons" / "icon.png").is_file()
    assert read_config(data)["key"] == KEY
    assert sorted(p.name for p in data.iterdir()) == [COPY_DIR]

    # A later call, with the failure gone, rebuilds the copy correctly.
    monkeypatch.setattr(shutil, "copy2", real_copy)
    sync_extension_copy(source, data, ADDRESS, KEY)
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
    assert (folder / "d.js").is_file()
    assert read_config(data)["stamp"] == config_stamp(ADDRESS, KEY)
    assert sorted(p.name for p in data.iterdir()) == [COPY_DIR]


def test_a_failed_first_copy_leaves_no_folder_and_a_stale_temporary_folder_is_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_source(tmp_path)
    data = tmp_path / "data"
    (data / (COPY_DIR + ".new")).mkdir(parents=True)  # left by an earlier crash
    ((data / (COPY_DIR + ".new")) / "junk.js").write_text("// junk", encoding="utf-8")

    def fail(src, dst, **kwargs):
        raise OSError("locked")

    monkeypatch.setattr(shutil, "copy2", fail)
    with pytest.raises(OSError):
        sync_extension_copy(source, data, ADDRESS, KEY)
    assert list(data.iterdir()) == []


def test_a_failed_config_write_leaves_no_part_file_holding_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(src, dst):
        raise OSError("cannot replace")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_extension_config(tmp_path, ADDRESS, KEY)
    assert list((tmp_path / COPY_DIR).iterdir()) == []


@pytest.fixture()
def client(tmp_path: Path):
    """The whole app on a scratch data folder (no lifespan: only the request path runs)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault, port=7790)
    app = create_app(settings)
    yield TestClient(app)
    app.state.engine.dispose()


def test_rotating_the_key_rewrites_the_config_with_a_new_stamp(client: TestClient) -> None:
    data = Path(client.app.state.settings.data_dir)
    first_key = client.get("/api/radar/import/button-key").json()["key"]
    write_extension_config(data, "http://127.0.0.1:7790", first_key)
    old = read_config(data)

    response = client.post("/api/radar/import/button-key/rotate")
    assert response.status_code == 200
    new_key = response.json()["key"]
    new = read_config(data)
    assert new_key != first_key
    assert new["key"] == new_key
    assert new["address"] == "http://127.0.0.1:7790"
    assert new["stamp"] != old["stamp"]

