"""Two small tables for the background filing run: open questions and plan proposals.

`FilingQuestion` holds the one question a background run may leave on a filed item ("Link this to
a project?") with up to three project names, the reader's answer and when the answer was applied.
`FilingProposal` holds one row of a "show me the plan first" run: what the item would become, where,
under which name, the project if any, and the reader's decision (approved or struck).

The tables are registered when `filing_queue` is imported (which `db.init_db` does), so they are
created on fresh databases and added to existing ones at the next start. `plain_line` is the one
cleaner for any text a tool call sends that the interface will show.
"""

import re
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

from spyglass_service.radar.models import utcnow
from spyglass_service.radar.text_clean import clean_line

# A markdown link becomes its text; emphasis marks, backticks, angle brackets and heading marks go.
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKUP = re.compile(r"[<>*`#|~\[\]]")


class FilingQuestion(SQLModel, table=True):
    """One open, answered or applied question on a filed item; `options` is a JSON list."""

    __tablename__ = "filing_question"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    options: str = "[]"
    asked_at: datetime = Field(default_factory=utcnow, index=True)
    # The reader's choice: one of the options or "No project"; None while open.
    answer: str | None = None
    answered_at: datetime | None = None
    # When a run added the link (or, for "No project", when the answer was given).
    applied_at: datetime | None = None


class FilingProposal(SQLModel, table=True):
    """One row of a plan: what an item would become and where; one row per item."""

    __tablename__ = "filing_proposal"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    becomes: str = ""
    place: str = ""
    name: str = ""
    project: str | None = None
    unsure: bool = False
    reason: str = ""
    proposed_at: datetime = Field(default_factory=utcnow, index=True)
    # "pending" until the reader approves the table; "approved" rows are filed by the next run.
    decision: str = "pending"
    decided_at: datetime | None = None


def plain_line(value: object, limit: int) -> str:
    """`value` as one plain line without markup, at most `limit` characters ("" for None).

    Control characters, line breaks and repeated spaces are folded by `clean_line`; a markdown
    link keeps only its text; markup characters are dropped. Used for every text a tool call
    supplies that the interface shows.
    """
    text = clean_line(value, limit * 2 if limit > 0 else limit)
    text = _MARKUP.sub("", _LINK.sub(r"\1", text))
    return clean_line(text, limit)


def as_utc(value: datetime | None) -> datetime | None:
    """A stored time as an aware UTC datetime (SQLite returns naive values)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
