"""The reader's project directory: which projects exist, and what each one is about.

Project names come from the vault's projects folder: the names of its immediate sub-folders, and
nothing else (no note is ever opened). Descriptions come only from the reader, who types one line
per project; they are stored in one document (RadarDoc key "projects", JSON in `body`):
  [{"name": str, "description": str}]
Only described projects are ever offered to an AI model (`described_projects`), so a project the
reader keeps confidential stays out of every prompt by having no description.
"""

import logging
import re
from pathlib import Path

from sqlmodel import Session

from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.text_clean import clean_line

logger = logging.getLogger(__name__)

DOC_KEY = "projects"
NAME_MAX = 80
DESCRIPTION_MAX = 200
MAX_ENTRIES = 100
# Most project folders a listing returns; a vault with more is listed in part.
MAX_LISTED = 200
# Names this short ("AI", "UX") match a note only with their exact case.
SHORT_NAME = 3


def _projects_folder(vault: Path) -> Path | None:
    """The vault's top-level folder whose name contains "projects" (any case), or None."""
    try:
        candidates = sorted(
            (p for p in vault.iterdir()
             if p.is_dir() and not p.name.startswith(".") and "projects" in p.name.lower()),
            key=lambda p: p.name.lower())
    except OSError:
        logger.warning("could not list the vault folder")
        return None
    return candidates[0] if candidates else None


def vault_project_names(settings) -> list[str]:
    """Names of the projects folder's immediate sub-folders, sorted; [] when there is none."""
    vault = getattr(settings, "vault_path", None)
    if vault is None or not Path(vault).is_dir():
        return []
    folder = _projects_folder(Path(vault))
    if folder is None:
        return []
    try:
        names = [p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        logger.warning("could not list the vault's projects folder")
        return []
    return sorted(names, key=str.lower)[:MAX_LISTED]


def _stored(session: Session) -> list[dict]:
    """The stored entries, each with a string name and description; [] when none or corrupt."""
    row = session.get(RadarDoc, DOC_KEY)
    raw = loads(row.body if row else None, [])
    if not isinstance(raw, list):
        return []
    return [{"name": str(e["name"]), "description": str(e.get("description") or "")}
            for e in raw if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"]]


def project_directory(session: Session, settings) -> list[dict]:
    """Every vault project with its description, then stored projects no longer in the vault.

    Each entry is {"name", "description", "in_vault"}.
    """
    stored = {e["name"].casefold(): e for e in _stored(session)}
    rows: list[dict] = []
    seen: set[str] = set()
    for name in vault_project_names(settings):
        entry = stored.get(name.casefold())
        rows.append({"name": name, "description": entry["description"] if entry else "",
                     "in_vault": True})
        seen.add(name.casefold())
    for key, entry in stored.items():
        if key not in seen:
            rows.append({**entry, "in_vault": False})
    return rows


def _validated(entries: object) -> list[dict]:
    """Cleaned entries with a description, or ValueError naming the first problem."""
    if not isinstance(entries, list):
        raise ValueError("The projects must be a list.")
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"At most {MAX_ENTRIES} projects can be described.")
    out: list[dict] = []
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("Each project needs a name.")
        name = clean_line(entry["name"], NAME_MAX + 1)
        description = clean_line(entry.get("description") or "", DESCRIPTION_MAX + 1)
        if not name:
            raise ValueError("Each project needs a name.")
        if len(name) > NAME_MAX:
            raise ValueError(f"A project name can be at most {NAME_MAX} characters.")
        if len(description) > DESCRIPTION_MAX:
            raise ValueError(f"A description can be at most {DESCRIPTION_MAX} characters.")
        if name.casefold() in names:
            raise ValueError(f"The project {name} is listed twice.")
        names.add(name.casefold())
        if description:
            out.append({"name": name, "description": description})
    return out


def save_project_directory(session: Session, entries: list[dict]) -> list[dict]:
    """Replace the stored directory and return what was stored.

    Names (at most 80 characters) and descriptions (at most 200) are cleaned to one plain line.
    Entries without a description are not stored: the vault listing already supplies the name.
    Raises ValueError, storing nothing, for more than 100 entries, a missing or repeated name or
    text over its limit.
    """
    cleaned = _validated(entries)
    row = session.get(RadarDoc, DOC_KEY)
    if row is None:
        row = RadarDoc(key=DOC_KEY, body=dumps(cleaned))
    row.body = dumps(cleaned)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return cleaned


def described_projects(session: Session) -> list[dict]:
    """The stored projects that have a description, as [{"name", "description"}].

    This is the only list of projects an AI model may be shown.
    """
    return [e for e in _stored(session) if e["description"].strip()]


def project_from_note(note: str | None, names: list[str]) -> str | None:
    """The project a note names (whole word, any case; short names need their exact case).

    When several names match, the longest wins, so "Beta Project" beats "Beta".
    """
    if not note:
        return None
    for name in sorted({n for n in names if n and n.strip()}, key=len, reverse=True):
        flags = 0 if len(name) <= SHORT_NAME else re.IGNORECASE
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", note, flags):
            return name
    return None
