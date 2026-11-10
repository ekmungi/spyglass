"""Tests for skill_sync: copy bundled repo skills into the vault's .claude/skills."""

from pathlib import Path

from spyglass_service.skill_sync import default_repo_skills_dir, sync_skills


def _make_repo_skill(root: Path, name: str, body: str) -> Path:
    """Create a repo-style skills/<name>/SKILL.md and return its path."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_fresh_copy_creates_vault_skill(tmp_path: Path) -> None:
    """A skill absent from the vault is copied in, and its name is reported."""
    repo = tmp_path / "skills"
    _make_repo_skill(repo, "spyglass", "# spyglass\nhello\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    synced = sync_skills(repo, vault)

    target = vault / ".claude" / "skills" / "spyglass" / "SKILL.md"
    assert target.read_text(encoding="utf-8") == "# spyglass\nhello\n"
    assert synced == ["spyglass"]


def test_unchanged_skill_is_skipped(tmp_path: Path) -> None:
    """A second sync with identical content copies nothing (returns no names)."""
    repo = tmp_path / "skills"
    _make_repo_skill(repo, "spyglass", "# spyglass\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    sync_skills(repo, vault)
    assert sync_skills(repo, vault) == []


def test_changed_skill_is_overwritten(tmp_path: Path) -> None:
    """When the repo copy changes, the vault copy is updated (repo wins)."""
    repo = tmp_path / "skills"
    src = _make_repo_skill(repo, "spyglass", "old\n")
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_skills(repo, vault)

    src.write_text("new\n", encoding="utf-8")
    synced = sync_skills(repo, vault)

    target = vault / ".claude" / "skills" / "spyglass" / "SKILL.md"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert synced == ["spyglass"]


def test_missing_vault_skills_dir_is_created(tmp_path: Path) -> None:
    """The vault's .claude/skills tree is created on demand."""
    repo = tmp_path / "skills"
    _make_repo_skill(repo, "spyglass", "x\n")
    vault = tmp_path / "vault"  # deliberately not created

    sync_skills(repo, vault)

    assert (vault / ".claude" / "skills" / "spyglass" / "SKILL.md").is_file()


def test_missing_repo_dir_returns_empty(tmp_path: Path) -> None:
    """No repo skills dir -> nothing to sync, no exception."""
    assert sync_skills(tmp_path / "does-not-exist", tmp_path / "vault") == []


def test_syncs_multiple_skills_sorted(tmp_path: Path) -> None:
    """Every repo skill is copied; report is deterministic (sorted)."""
    repo = tmp_path / "skills"
    _make_repo_skill(repo, "spyglass", "a\n")
    _make_repo_skill(repo, "spyglass-preferences", "b\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    assert sync_skills(repo, vault) == ["spyglass", "spyglass-preferences"]


def test_per_skill_io_error_is_swallowed(tmp_path: Path, monkeypatch) -> None:
    """A failure writing one skill is logged and skipped, never raised (startup must not die)."""
    repo = tmp_path / "skills"
    _make_repo_skill(repo, "spyglass", "a\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    import spyglass_service.skill_sync as mod

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod.shutil, "copyfile", _boom)
    # Must not raise; the skill simply is not reported as synced.
    assert sync_skills(repo, vault) == []


def test_dir_without_skill_md_is_ignored(tmp_path: Path) -> None:
    """A skill folder lacking SKILL.md is skipped, not an error."""
    repo = tmp_path / "skills"
    (repo / "empty").mkdir(parents=True)  # no SKILL.md inside
    _make_repo_skill(repo, "spyglass", "x\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    assert sync_skills(repo, vault) == ["spyglass"]


def test_default_repo_skills_dir_points_at_repo_skills() -> None:
    """The default resolves to the repo's top-level skills/ dir (holds the spyglass skill)."""
    root = default_repo_skills_dir()
    assert root.name == "skills"
    assert (root / "spyglass" / "SKILL.md").is_file()
