"""Tests for vault reads (interest profile) and atomic briefing writes."""

from pathlib import Path

import frontmatter

from spyglass_service.config import Settings
from spyglass_service.vault import read_interest_profile, read_preferences, save_briefing


def test_read_preferences_returns_note_or_default(tmp_path: Path) -> None:
    """The learned-preferences note is read like the interest profile, with a default."""
    note = tmp_path / "preferences.md"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", preferences_note_path=note)
    assert "preferences" in read_preferences(settings).lower()  # absent -> guidance
    note.write_text("Prefer deep agentic-AI papers.", encoding="utf-8")
    assert "agentic-AI" in read_preferences(settings)


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        vault_path=vault,
        interest_note_path=vault / "interests.md",
    )


def test_interest_profile_reads_the_configured_note(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.interest_note_path.write_text("I care about agentic AI.", encoding="utf-8")
    assert "agentic AI" in read_interest_profile(settings)


def test_missing_interest_note_returns_helpful_default(tmp_path: Path) -> None:
    """No profile yet: curation still works, with guidance instead of a crash."""
    settings = make_settings(tmp_path)
    text = read_interest_profile(settings)
    assert "interest" in text.lower()


def test_save_briefing_writes_frontmatter_markdown_into_the_vault(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    path = save_briefing(settings, title="Local-first sync", markdown="# Body\n\nText.")
    assert path.is_file()
    assert settings.vault_path in path.parents
    post = frontmatter.load(path)
    assert post["title"] == "Local-first sync"
    assert post["type"] == "research"
    assert "# Body" in post.content


def test_briefing_filenames_are_deterministic_and_windows_safe(tmp_path: Path) -> None:
    """Same title on the same day overwrites; illegal characters are stripped."""
    settings = make_settings(tmp_path)
    first = save_briefing(settings, title='A: "risky" <title>?', markdown="one")
    second = save_briefing(settings, title='A: "risky" <title>?', markdown="two")
    assert first == second
    assert not any(ch in first.name for ch in '<>:"/\\|?*')
    assert frontmatter.load(first).content == "two"


def test_save_briefing_without_vault_path_fails_loudly(tmp_path: Path) -> None:
    """Writing into an unconfigured vault must be an error, never a guess."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    try:
        save_briefing(settings, title="x", markdown="y")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "vault" in str(exc).lower()
