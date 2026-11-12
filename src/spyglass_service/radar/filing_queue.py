"""The "To file" queue: items the reader marked for filing in their notes vault.

One click in Spyglass puts an item here; nothing is written to the vault. Later, one Claude Code
session opened in the vault reads the queue (the `radar_filing_queue` tool) and files the whole
batch with the vault's own skills after one approval, or a hidden background run does it by
itself (`filing_run`, when the reader switched that on). Each row holds the reader's choices for the
item: the kind of note, an optional project and a one-line note. A row leaves the queue when the
item is recorded as filed (see `filed.record_filed`) or when the reader removes it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Field, Session, SQLModel, func, select

from spyglass_service.models import Item
# Registers the background run's question and proposal tables with this one (db.init_db imports
# this module), so they are created on fresh databases and added to existing ones.
from spyglass_service.radar.filing_tables import FilingProposal
from spyglass_service.radar.models import utcnow
from spyglass_service.radar.projects import project_directory
from spyglass_service.radar.text_clean import clean_line

logger = logging.getLogger(__name__)

# The kinds of note the reader can ask for. Defined here (not in claude_bridge) because the item
# serializer imports this module, and claude_bridge imports the serializer.
FILE_KINDS = ("resource", "to explore", "learning", "feature idea")
DEFAULT_KIND = "resource"
NOTE_MAX = 500
PROJECT_MAX = 80


class FilingRow(SQLModel, table=True):
    """One queued item; `item_id` is unique, so queuing twice changes the row."""

    __tablename__ = "filing_queue"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    kind: str = DEFAULT_KIND
    project: str | None = None
    note: str = ""
    requested_at: datetime = Field(default_factory=utcnow, index=True)


@dataclass(frozen=True)
class QueueEntry:
    """A queued item with the reader's choices, detached from the database session."""

    item_id: int
    kind: str
    project: str | None
    note: str
    requested_at: datetime


def _entry(row: FilingRow) -> QueueEntry:
    """The detached copy of a row."""
    return QueueEntry(row.item_id, row.kind, row.project, row.note, row.requested_at)


def check_project(session: Session, settings, project: str | None) -> str | None:
    """The listed project name `project` stands for (any case), None for none given.

    Raises ValueError with a plain message when the name is not one of the reader's projects.
    """
    name = clean_line(project, PROJECT_MAX + 1)
    if not name:
        return None
    for entry in project_directory(session, settings):
        if entry["name"].casefold() == name.casefold():
            return entry["name"]
    raise ValueError(f"\"{clean_line(name, PROJECT_MAX)}\" is not one of your projects.")


def enqueue(engine: Engine, item_id: int, *, kind: str = DEFAULT_KIND,
            project: str | None = None, note: str | None = None) -> QueueEntry:
    """Queue the item, or change its row when it is already queued; returns the row.

    `kind` must be one of `FILE_KINDS` (ValueError otherwise). The note is cleaned to one line of
    at most 500 characters. A repeated call keeps the original queue position.
    """
    if kind not in FILE_KINDS:
        raise ValueError("Unknown filing kind.")
    project_name = clean_line(project, PROJECT_MAX) or None
    choices = (kind, project_name, clean_line(note, NOTE_MAX))
    with Session(engine) as session:
        row = session.exec(select(FilingRow).where(FilingRow.item_id == item_id)).first()
        if row is None:
            row = FilingRow(item_id=item_id)
        elif (row.kind, row.project, row.note) != choices:
            # A plan row made for the old choices no longer says what the reader wants.
            for proposal in session.exec(select(FilingProposal).where(
                    FilingProposal.item_id == item_id)).all():
                session.delete(proposal)
        row.kind, row.project, row.note = choices
        session.add(row)
        session.commit()
        session.refresh(row)
        return _entry(row)


def dequeue(engine: Engine, item_id: int) -> bool:
    """Take the item out of the queue (and its plan row, if any); False when it was not there."""
    with Session(engine) as session:
        row = session.exec(select(FilingRow).where(FilingRow.item_id == item_id)).first()
        for proposal in session.exec(select(FilingProposal).where(
                FilingProposal.item_id == item_id)).all():
            session.delete(proposal)
        if row is None:
            session.commit()
            return False
        session.delete(row)
        session.commit()
        return True


def waiting(engine: Engine) -> list[QueueEntry]:
    """Every queued item, oldest request first."""
    with Session(engine) as session:
        rows = session.exec(select(FilingRow).order_by(FilingRow.requested_at, FilingRow.id)).all()
        return [_entry(r) for r in rows]


def count(engine: Engine) -> int:
    """How many items are waiting."""
    with Session(engine) as session:
        return int(session.exec(select(func.count()).select_from(FilingRow)).one())


def queued_ids(session: Session, item_ids: list[int]) -> set[int]:
    """The ids among `item_ids` that are in the queue (one query)."""
    if not item_ids:
        return set()
    return set(session.exec(select(FilingRow.item_id).where(FilingRow.item_id.in_(item_ids))).all())


def waiting_condition():
    """A SQL condition true for queued items (for a `filing=waiting` feed filter)."""
    return Item.id.in_(select(FilingRow.item_id))
