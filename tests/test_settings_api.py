"""Tests for the settings API: editable runtime settings with overlay persistence."""

from pathlib import Path

from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings, apply_overlay


def make_client(tmp_path: Path, **kwargs) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", **kwargs)
    return TestClient(create_app(settings))


def test_get_settings_returns_editable_subset(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/settings").json()
    assert body["relevance_threshold"] == "medium"
    assert body["fulltext_refresh_hours"] == 24.0
    assert body["relevance_model"] == "haiku"
    assert body["port"] == 7777
    assert body["vault_path"] is None


def test_the_removed_vault_folder_setting_is_not_served_or_accepted(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert "radar_vault_subdir" not in client.get("/api/settings").json()
        client.patch("/api/settings", json={"radar_vault_subdir": "Anywhere"})
        assert "radar_vault_subdir" not in client.get("/api/settings").json()
    overlay = tmp_path / "data" / "settings.json"
    assert not overlay.is_file() or "radar_vault_subdir" not in overlay.read_text(encoding="utf-8")


def test_get_settings_includes_yt_transcribe_cmd(tmp_path: Path) -> None:
    """The yt-transcribe CLI path is part of the editable settings."""
    with make_client(tmp_path) as client:
        body = client.get("/api/settings").json()
    assert "yt_transcribe_cmd" in body


def test_startup_resolves_explicit_yt_transcribe_cmd(tmp_path: Path) -> None:
    """An explicit yt_transcribe_cmd is resolved into documents at startup."""
    from spyglass_service import documents

    with make_client(tmp_path, yt_transcribe_cmd="/custom/yt-transcribe"):
        assert documents._YT_CMD == "/custom/yt-transcribe"


def test_patch_yt_transcribe_cmd_persists_and_applies_live(tmp_path: Path) -> None:
    """Patching the CLI path persists AND applies live to the transcript path."""
    from spyglass_service import documents

    with make_client(tmp_path) as client:
        body = client.patch("/api/settings", json={"yt_transcribe_cmd": "/opt/yt-transcribe"}).json()
        assert body["yt_transcribe_cmd"] == "/opt/yt-transcribe"
        assert documents._YT_CMD == "/opt/yt-transcribe"  # applied without a restart
    with make_client(tmp_path) as client:
        assert client.get("/api/settings").json()["yt_transcribe_cmd"] == "/opt/yt-transcribe"


def test_patch_settings_updates_and_persists(tmp_path: Path) -> None:
    """A patched value survives a service restart via the data-dir overlay."""
    with make_client(tmp_path) as client:
        patched = client.patch(
            "/api/settings",
            json={"relevance_threshold": "low", "fulltext_refresh_hours": 6, "relevance_model": "sonnet"},
        ).json()
        assert patched["relevance_threshold"] == "low"
    with make_client(tmp_path) as client:
        body = client.get("/api/settings").json()
    assert body["relevance_threshold"] == "low"
    assert body["fulltext_refresh_hours"] == 6.0
    assert body["relevance_model"] == "sonnet"


def test_note_paths_serialize_vault_relative(tmp_path: Path) -> None:
    """Note paths display and edit as vault-root-relative when under the vault."""
    vault = tmp_path / "vault"
    vault.mkdir()
    with make_client(tmp_path, vault_path=vault) as client:
        client.patch(
            "/api/settings", json={"interest_note_path": "00 INBOX/Spyglass/interests.md"}
        )
        body = client.get("/api/settings").json()
    assert body["interest_note_path"] == "00 INBOX/Spyglass/interests.md"


def test_patch_rejects_unknown_threshold(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert (
            client.patch("/api/settings", json={"relevance_threshold": "extreme"}).status_code
            == 422
        )


def test_apply_overlay_is_noop_without_file(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert apply_overlay(settings).relevance_threshold == "medium"
