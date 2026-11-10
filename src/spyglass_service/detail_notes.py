"""Detailed notes: Spyglass writes them, one folder per day, and removes them.

A background job composes the note and hands it to `job_save_detail`; Spyglass writes
the file, so the run itself never writes into the vault. Delete moves a note that is still in
the Brief notes folder to the vault's `.trash` folder, as Obsidian does, and counts as a thumbs
down. A note that has been filed lives in the user's own folders and is not deleted from here.
"""

import os
import re
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

import frontmatter
from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.feedback import set_feedback
from spyglass_service.models import Card, Item

# Characters Windows refuses in file names, plus those Obsidian reads as link syntax.
_ILLEGAL = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
NAME_MAX = 100
# Names Windows reserves for devices, whatever the extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
# Note bodies Obsidian would run as code when the note is read (Dataview JS): kept as text.
_DATAVIEW_JS = re.compile(r"^(\s*(?:```|~~~)\s*)dataviewjs\b", re.IGNORECASE | re.MULTILINE)
_INLINE_JS = re.compile(r"`\$=")
# How often to look through the vault again for a note that is not where the card says.
RELOCATE_EVERY_S = 300
_ITEM_FIELD = re.compile(r"^spyglass_item:\s*(\d+)\s*$", re.MULTILINE)


class NoteNotRemovable(Exception):
    """The card's note is not a detailed note in the Brief notes folder, or is missing."""


def detail_root(settings: Settings) -> Path:
    if settings.vault_path is None:
        raise ValueError("vault_path is not configured; refusing to guess where to write")
    return settings.vault_path / settings.detail_notes_subdir


def note_filename(title: str) -> str:
    """A readable, Windows-safe note name from the title (without .md)."""
    clean = " ".join(_ILLEGAL.sub(" ", title).split()).strip(" .")
    if len(clean) > NAME_MAX:
        clean = clean[:NAME_MAX].rsplit(" ", 1)[0].strip(" .") or clean[:NAME_MAX]
    if clean.split(".")[0].upper() in _RESERVED:
        clean = f"{clean} note"
    return clean or "Spyglass item"


def neutralize_scripts(markdown: str) -> str:
    """Keep code a run wrote from running in Obsidian: Dataview JS blocks and inline `$= ...`
    queries become plain code. A note's text can come from an article, which must not be able
    to run code on the user's computer when the note is opened."""
    return _INLINE_JS.sub("`$ =", _DATAVIEW_JS.sub(r"\1js", markdown))


def local_today() -> date:
    """The user's date, for day folders: a note written at 23:30 belongs to that evening."""
    return datetime.now().astimezone().date()


def is_inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def in_detail_folder(settings: Settings, note_path: str | None) -> bool:
    """Whether a card's note is in the Brief notes folder (where Prepare detail writes it)."""
    if not note_path or settings.vault_path is None:
        return False
    return is_inside(Path(note_path), detail_root(settings))


def spyglass_folders(settings: Settings) -> list[Path]:
    """The vault folders Spyglass writes its own output to: Brief notes (and its parent when that
    is a Spyglass folder), and the briefing and document folders. A note there is not filed in
    the user's own knowledge yet."""
    if settings.vault_path is None:
        return []
    vault = settings.vault_path
    root = detail_root(settings)
    folders = [root, vault / settings.briefing_subdir, vault / settings.documents_subdir]
    if root.parent != vault and root.parent.name.lower() == "spyglass":
        folders.append(root.parent)
    return folders


def folder_names(settings: Settings) -> str:
    """Spyglass's own folders, vault-relative and comma-separated, for the filing steps."""
    vault = settings.vault_path
    names = [f.relative_to(vault).as_posix() for f in spyglass_folders(settings)] if vault else []
    return ", ".join(dict.fromkeys(names))


def in_spyglass_folder(settings: Settings, note_path: str | Path | None) -> bool:
    """Whether a note sits in one of Spyglass's own folders, so it still needs filing."""
    if not note_path:
        return False
    return any(is_inside(Path(note_path), folder) for folder in spyglass_folders(settings))


def vault_relative(settings: Settings, note_path: str | None) -> str | None:
    """A note path as the user sees it in the vault, or as stored when outside it."""
    if not note_path:
        return None
    if settings.vault_path is not None and is_inside(Path(note_path), settings.vault_path):
        return Path(note_path).resolve().relative_to(settings.vault_path.resolve()).as_posix()
    return note_path


def _atomic_write(target: Path, content: str) -> None:
    """Temp file in the same folder, fsync, then replace: never a half-written note."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_detail_note(settings: Settings, engine: Engine, card_id: int, title: str,
                      markdown: str, today: date | None = None) -> Path:
    """Write (or rewrite) a card's detailed note and record it on the card; return its path.

    A card whose note is already in the Brief notes folder keeps that file, so preparing the
    detail again replaces it rather than adding a second note. Otherwise the note goes in
    today's folder, named after the title, with the code added if that name is taken.
    """
    root = detail_root(settings)
    day = today or local_today()
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, card.item_id) if card else None
        if card is None or item is None:
            raise LookupError(f"no card {card_id}")
        current = Path(card.briefing_path) if card.briefing_path else None
        if current is not None and current.is_file() and is_inside(current, root):
            target = current
        else:
            folder = root / day.isoformat()
            name = note_filename(title)
            target = folder / f"{name}.md"
            counter = 1
            while target.exists():
                suffix = f" ({card_id})" if counter == 1 else f" ({card_id}-{counter})"
                target = folder / f"{name}{suffix}.md"
                counter += 1
        post = frontmatter.Post(
            neutralize_scripts(markdown).strip() + "\n",
            title=" ".join(title.split()),
            type="spyglass-detail",
            source=item.url,
            spyglass_item=card_id,
            created=day.isoformat(),
            tags=["spyglass"],
        )
        _atomic_write(target, frontmatter.dumps(post) + "\n")
        card.briefing_path = str(target)
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
    return target


def delete_detail_note(settings: Settings, engine: Engine, card_id: int) -> str | None:
    """Move a card's unfiled detailed note to the vault's .trash, clear it from the card and
    record a thumbs down. Returns where it went (vault-relative), or None when the file was
    already gone (the card is cleared, and no thumbs down is recorded). Raises
    NoteNotRemovable."""
    if settings.vault_path is None:
        raise NoteNotRemovable("The vault folder is not set.")
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            raise LookupError(f"no card {card_id}")
        note = Path(card.briefing_path) if card.briefing_path else None
        if note is None or not in_spyglass_folder(settings, note):
            raise NoteNotRemovable(
                "Only a note still in Spyglass's own folders is deleted from Spyglass. Delete a "
                "filed note in Obsidian.")
        target: Path | None = None
        if note.is_file():
            trash = settings.vault_path / ".trash"
            trash.mkdir(parents=True, exist_ok=True)
            target = trash / note.name
            counter = 2
            while target.exists():
                target = trash / f"{note.stem} {counter}{note.suffix}"
                counter += 1
            os.replace(note, target)
        card.briefing_path = None
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
    if target is None:
        return None
    set_feedback(engine, card_id, "down")
    return target.relative_to(settings.vault_path).as_posix()


_last_search: dict[int, float] = {}


def find_note_by_item(vault: Path, card_id: int) -> Path | None:
    """The vault note whose properties say `spyglass_item: <card_id>`, wherever it was moved.
    Hidden folders (.obsidian, .trash) are skipped; only each note's first lines are read."""
    for path in vault.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                head = handle.read(2048)
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        end = head.find("\n---", 3)
        match = _ITEM_FIELD.search(head[: end if end > 0 else len(head)])
        if match and int(match.group(1)) == card_id:
            return path
    return None


def relocate_note(settings: Settings, engine: Engine, card_id: int, force: bool = False) -> bool:
    """When a card's note is no longer where the card says (moved in Obsidian, or by a filing run
    that never reported), find it by its spyglass_item property and record the new place.
    Looks at most every few minutes per card unless forced. True when the note was found."""
    if settings.vault_path is None:
        return False
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None or not card.briefing_path or Path(card.briefing_path).is_file():
            return False
    now = time.monotonic()
    if not force and now - _last_search.get(card_id, -RELOCATE_EVERY_S) < RELOCATE_EVERY_S:
        return False
    _last_search[card_id] = now
    found = find_note_by_item(settings.vault_path, card_id)
    if found is None:
        return False
    with Session(engine) as session:
        card = session.get(Card, card_id)
        card.briefing_path = str(found)
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
    return True
