"""Tests for yt-transcribe CLI auto-discovery."""

import json
from pathlib import Path

from spyglass_service.yt_discovery import discover_yt_transcribe


def _write_plugin_config(vault: Path, executable_path: str) -> None:
    """Seed the YouTube Transcribe plugin's data.json under a vault's .obsidian dir."""
    plugin_dir = vault / ".obsidian" / "plugins" / "youtube-transcribe"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "data.json").write_text(
        json.dumps({"executablePath": executable_path}), encoding="utf-8"
    )


def test_discover_reads_the_obsidian_plugin_configured_path(tmp_path: Path) -> None:
    """When the YouTube Transcribe plugin points at a real binary, Spyglass reuses that path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    exe = tmp_path / "tools" / "yt-transcribe.exe"
    exe.parent.mkdir()
    exe.write_text("binary")
    _write_plugin_config(vault, str(exe))

    assert discover_yt_transcribe(vault, home=tmp_path, which=lambda _: None) == str(exe)


def test_discover_skips_plugin_bare_name_and_uses_path(tmp_path: Path) -> None:
    """A bare 'yt-transcribe' in the plugin config is a PATH ref -> fall through to which()."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_plugin_config(vault, "yt-transcribe")  # not a file path

    assert discover_yt_transcribe(vault, home=tmp_path, which=lambda _: "/usr/bin/yt-transcribe") == (
        "/usr/bin/yt-transcribe"
    )


def test_discover_uses_path_when_no_plugin(tmp_path: Path) -> None:
    """With no plugin config, a binary on PATH is used."""
    assert discover_yt_transcribe(
        tmp_path, home=tmp_path, which=lambda name: f"/bin/{name}"
    ) == "/bin/yt-transcribe"


def test_discover_uses_known_local_bin_location(tmp_path: Path) -> None:
    """Not on PATH but installed at ~/.local/bin -> discovered there (the common uv-tool case)."""
    local = tmp_path / ".local" / "bin"
    local.mkdir(parents=True)
    exe = local / "yt-transcribe.exe"
    exe.write_text("binary")

    assert discover_yt_transcribe(None, home=tmp_path, which=lambda _: None) == str(exe)


def test_discover_returns_none_when_absent(tmp_path: Path) -> None:
    """Nothing configured, not on PATH, no known install -> None (caller uses the fallback)."""
    assert discover_yt_transcribe(tmp_path, home=tmp_path, which=lambda _: None) is None
