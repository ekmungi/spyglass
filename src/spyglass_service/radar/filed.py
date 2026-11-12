"""Where the reader's own Claude session filed an item in the vault.

Spyglass never files into a project itself. After the reader's session has filed an item, it
calls the `radar_mark_filed` tool, which lands here: the path is checked (relative, inside the
vault folder, no ".." parts, and the file exists) and stored in the item's ItemExtra data under
"filed": {"path", "project", "at", "best_guess"}, with a Signal(kind="vault", value="filed").
`best_guess` is true when a background run placed the note by its own best judgement because
the reader had not said where it goes (shown as such under "Filed recently").
"""

import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import func
from sqlalchemy import Engine
from sqlmodel import Session, delete, select

from spyglass_service.models import Item
from spyglass_service.radar.filing_queue import FilingRow
from spyglass_service.radar.filing_tables import FilingProposal
from spyglass_service.radar.models import ItemExtra, Signal, dumps, loads, utcnow
from spyglass_service.radar.text_clean import clean_line

logger = logging.getLogger(__name__)

PROJECT_MAX = 80
PATH_MAX = 500
_DRIVE = re.compile(r"^[A-Za-z]:")


def _relative_parts(path: object) -> list[str] | None:
    """The parts of a vault-relative path, or None for anything absolute, empty or escaping."""
    if not isinstance(path, str):
        return None
    raw = path.strip()
    if not raw or len(raw) > PATH_MAX:
        return None
    if any(unicodedata.category(c) == "Cc" for c in raw):
        return None
    if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
        return None
    parts = [p for p in re.split(r"[\\/]+", raw) if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    return parts


def vault_relative_parts(path: object) -> list[str] | None:
    """The parts of a vault-relative path, or None for anything absolute, empty or escaping."""
    return _relative_parts(path)


def _error(code: str, detail: str) -> dict:
    """A tool error payload."""
    return {"error": code, "detail": detail}


def record_filed(engine: Engine, settings, item_id: int, path: str,
                 project: str | None = None, best_guess: bool = False) -> dict:
    """Record where an item was filed; returns {"recorded", "path", "project", "best_guess"} or
    an error. The item leaves the queue, and its plan row (if any) goes with it.

    Errors: "no_vault" (no vault folder set), "not_found" (unknown item), "invalid_path" (not a
    relative path inside the vault) and "no_file" (nothing there, or a folder).
    """
    vault = getattr(settings, "vault_path", None)
    if vault is None:
        return _error("no_vault", "Spyglass has no vault folder set.")
    with Session(engine) as session:
        if session.get(Item, item_id) is None:
            return _error("not_found", f"No Spyglass item {item_id}.")
    parts = _relative_parts(path)
    if parts is None:
        return _error("invalid_path", "Give the path relative to the vault folder, such as "
                                      "01 PROJECTS/Name/Note.md, without '..'.")
    root = Path(vault).resolve()
    target = Path(vault, *parts).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _error("invalid_path", "That path leads outside the vault folder.")
    if not target.is_file():
        return _error("no_file", "There is no file at that path in the vault.")
    relative = "/".join(parts)
    project_name = clean_line(project, PROJECT_MAX) or None
    entry = {"path": relative, "project": project_name, "at": utcnow().isoformat(),
             "best_guess": bool(best_guess)}
    with Session(engine) as session:
        row = session.exec(select(ItemExtra).where(ItemExtra.item_id == item_id)).first()
        data = loads(row.data, {}) if row else {}
        merged = {**(data if isinstance(data, dict) else {}), "filed": entry}
        if row is None:
            row = ItemExtra(item_id=item_id, data=dumps(merged))
        row.data = dumps(merged)
        session.add(row)
        session.add(Signal(item_id=item_id, kind="vault", value="filed"))
        # Filed items leave the "To file" queue in the same transaction.
        session.exec(delete(FilingRow).where(FilingRow.item_id == item_id))
        session.exec(delete(FilingProposal).where(FilingProposal.item_id == item_id))
        session.commit()
    return {"recorded": True, "path": relative, "project": project_name,
            "best_guess": bool(best_guess)}


def filed_condition():
    """A SQL condition true for items with a recorded filing place (for a `filed=true` filter)."""
    return Item.id.in_(
        select(ItemExtra.item_id).where(
            func.json_extract(ItemExtra.data, "$.filed.path").is_not(None)))
