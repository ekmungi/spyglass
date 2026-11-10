"""Vault integration: read the interest profile, write briefings atomically."""

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from spyglass_service.config import Settings

_DEFAULT_PROFILE = (
    "No interest profile note is configured yet. Curate conservatively: keep items "
    "that look substantive (research, engineering, regulation) and drop noise."
)

# Characters not allowed in Windows filenames.
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def read_interest_profile(settings: Settings) -> str:
    """Return the user's interest note text, or safe default guidance if absent."""
    note = settings.interest_note_path
    if note is None or not note.is_file():
        return _DEFAULT_PROFILE
    return note.read_text(encoding="utf-8")


_DEFAULT_PREFERENCES = (
    "No learned preferences note is configured yet. Lean on the interest profile; this "
    "note accumulates what the user keeps vs dismisses over time."
)


def read_preferences(settings: Settings) -> str:
    """Return the user's learned-preferences note text, or safe default if absent.

    Resolves through the fixed-default path so it works even when no vault note
    is configured; the file may not exist yet (the preferences skill creates it).
    """
    note = settings.effective_preferences_note_path
    if not note.is_file():
        return _DEFAULT_PREFERENCES
    return note.read_text(encoding="utf-8")


def _slugify(title: str) -> str:
    """Windows-safe, deterministic slug for briefing filenames."""
    cleaned = _ILLEGAL.sub("", title).strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-") or "briefing"


def save_briefing(settings: Settings, title: str, markdown: str) -> Path:
    """Write a briefing note into the vault atomically; return its path.

    Deterministic filename (date + slug) so a re-run overwrites rather than
    duplicating (friendly to a cloud-synced vault folder). Temp file in the same directory + fsync +
    os.replace keeps the write atomic on NTFS.
    """
    if settings.vault_path is None:
        raise ValueError("vault_path is not configured; refusing to guess where to write")

    target_dir = settings.vault_path / settings.briefing_subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y%m%d")
    target = target_dir / f"{today}-{_slugify(title)}.md"

    post = frontmatter.Post(
        markdown,
        title=title,
        type="research",
        created=datetime.now(UTC).strftime("%Y-%m-%d"),
        source="spyglass",
    )
    content = frontmatter.dumps(post)

    fd, tmp_name = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        # Never leave temp litter in the vault on failure.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return target
