"""Sync bundled repo skills into the vault's `.claude/skills` at service startup.

A dashboard-launched Claude session loads its skills from the vault's `.claude/skills/`. Before
this, those were a hand-copied snapshot that silently drifted from the repo `skills/` sources. On
each service start we mirror the repo's `skills/*/SKILL.md` into the vault (one-way, repo wins,
copy-on-diff) so a spawned session always runs the current instructions. Failures are non-fatal:
stale skills beat a service that will not start.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Subpath under the vault where Claude Code discovers project skills.
_VAULT_SKILLS_SUBPATH = (".claude", "skills")


def default_repo_skills_dir() -> Path:
    """Absolute path to the repo's top-level `skills/` directory.

    This module lives at `src/spyglass_service/skill_sync.py`, so the repo root is two parents up
    and `skills/` sits beside `src/`. The dev tool runs from a source checkout, so this resolves
    correctly at runtime.

    Returns:
        The `<repo>/skills` path (not guaranteed to exist).
    """
    return Path(__file__).resolve().parents[2] / "skills"


def sync_skills(repo_skills_dir: Path, vault_path: Path) -> list[str]:
    """Mirror repo `skills/<name>/SKILL.md` into `<vault>/.claude/skills/<name>/SKILL.md`.

    One-way and idempotent: a skill is (re)written only when the vault copy is missing or its bytes
    differ from the repo copy, so an unchanged tree is a no-op. Never raises -- a per-skill IO
    error is logged and that skill is skipped, so a bad vault path cannot take down startup.

    Args:
        repo_skills_dir: The repo's `skills/` directory (source of truth).
        vault_path: The vault root; skills land under its `.claude/skills/`.

    Returns:
        The names of skills actually written this call (created or updated), sorted. Empty when
        nothing changed or the repo dir is absent.
    """
    if not repo_skills_dir.is_dir():
        return []

    vault_skills_dir = vault_path.joinpath(*_VAULT_SKILLS_SUBPATH)
    synced: list[str] = []

    for skill_dir in sorted(p for p in repo_skills_dir.iterdir() if p.is_dir()):
        source = skill_dir / "SKILL.md"
        if not source.is_file():
            continue
        target = vault_skills_dir / skill_dir.name / "SKILL.md"
        try:
            if not _needs_write(source, target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            synced.append(skill_dir.name)
        except OSError:
            # Non-fatal: a stale (or missing) vault copy of one skill must not stop the service.
            logger.exception("skill sync: failed to write %s", target)

    return synced


def _needs_write(source: Path, target: Path) -> bool:
    """True when the target is absent or its content differs from the source (copy-on-diff)."""
    if not target.is_file():
        return True
    return source.read_bytes() != target.read_bytes()
