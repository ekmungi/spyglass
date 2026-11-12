"""The one question a background filing run may leave on an item: "Link this to a project?".

A run files every queued item first and never waits. When the reader chose no project but a link to
one of their projects is plausible, the run calls `radar_filing_ask` with up to three project names;
Spyglass fixes the question text and adds "No project". The reader answers all open questions in one
list and submits once (`submit_answers`); "No project" is settled at once, a project choice waits for
the next run, which adds the link through the vault's skills and calls `radar_filing_applied`
(`mark_applied`). A question nobody answers changes nothing and is removed after 14 days.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.filing_queue import FilingRow
from spyglass_service.radar.filing_tables import FilingQuestion, as_utc, plain_line
from spyglass_service.radar.models import ItemExtra, dumps, loads, utcnow
from spyglass_service.radar.projects import project_directory

logger = logging.getLogger(__name__)

QUESTION = "Link this to a project?"
NO_PROJECT = "No project"
MAX_PROJECTS = 3
EXPIRE_DAYS = 14
NAME_MAX = 80


def _error(code: str, detail: str) -> dict:
    """A tool error payload."""
    return {"error": code, "detail": detail}


def filed_entry(session: Session, item_id: int) -> dict | None:
    """The item's recorded filing place {"path", "project", "at", ...}, or None."""
    row = session.exec(select(ItemExtra).where(ItemExtra.item_id == item_id)).first()
    data = loads(row.data, {}) if row else {}
    entry = data.get("filed") if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) and entry.get("path") else None


def _canonical_options(session: Session, settings, options: object) -> list[str] | None:
    """The listed project names `options` stand for (1 to 3, no repeats), or None if invalid."""
    if not isinstance(options, list):
        return None
    listed = {e["name"].casefold(): e["name"] for e in project_directory(session, settings)}
    names: list[str] = []
    for option in options:
        text = plain_line(option, NAME_MAX + 1) if isinstance(option, str) else ""
        if text.casefold() == NO_PROJECT.casefold():
            continue
        name = listed.get(text.casefold())
        if name is None:
            return None
        if name not in names:
            names.append(name)
    return names if 1 <= len(names) <= MAX_PROJECTS else None


def ask(engine: Engine, settings, item_id: int, options: object, *,
        now: datetime | None = None) -> dict:
    """Leave the fixed question on a filed or queued item; returns the stored question or an error.

    Errors: "not_found", "not_filed" (neither filed nor queued), "project_chosen" (the reader
    already chose a project) and "invalid_options" (not 1 to 3 of the reader's listed projects).
    An open question on the same item is replaced.
    """
    with Session(engine) as session:
        if session.get(Item, item_id) is None:
            return _error("not_found", f"No Spyglass item {item_id}.")
        queued = session.exec(select(FilingRow).where(FilingRow.item_id == item_id)).first()
        filed = filed_entry(session, item_id)
        if queued is None and filed is None:
            return _error("not_filed", "Ask only about an item in the queue or one you filed.")
        if (queued is not None and queued.project) or (filed and filed.get("project")):
            return _error("project_chosen", "The reader already chose the project for this item.")
        names = _canonical_options(session, settings, options)
        if names is None:
            return _error("invalid_options", "Give one to three of the reader's listed project "
                                             "names; Spyglass adds \"No project\" itself.")
        for old in session.exec(select(FilingQuestion).where(
                FilingQuestion.item_id == item_id, FilingQuestion.answer.is_(None))).all():
            session.delete(old)
        session.add(FilingQuestion(item_id=item_id, options=dumps(names), asked_at=now or utcnow()))
        session.commit()
    return {"asked": True, "item_id": item_id, "question": QUESTION,
            "options": [*names, NO_PROJECT]}


def _cutoff(now: datetime | None) -> datetime:
    """The oldest asking time that is still open."""
    return (now or utcnow()) - timedelta(days=EXPIRE_DAYS)


def _options(row: FilingQuestion) -> list[str]:
    """The stored project names plus "No project"."""
    names = loads(row.options, [])
    return [*(n for n in names if isinstance(n, str)), NO_PROJECT]


def open_questions(engine: Engine, *, now: datetime | None = None) -> list[dict]:
    """Unanswered questions younger than 14 days, oldest first: {"id", "item_id", "question",
    "options", "asked_at"}."""
    cutoff = _cutoff(now)
    with Session(engine) as session:
        rows = session.exec(select(FilingQuestion).where(FilingQuestion.answer.is_(None))
                            .order_by(FilingQuestion.asked_at, FilingQuestion.id)).all()
        return [{"id": r.id, "item_id": r.item_id, "question": QUESTION, "options": _options(r),
                 "asked_at": as_utc(r.asked_at).isoformat()}
                for r in rows if as_utc(r.asked_at) >= cutoff]


def submit_answers(engine: Engine, answers: list[tuple[int, str]], *,
                   now: datetime | None = None) -> dict:
    """Store every answer of one submit, or none of them; returns {"answered": n}.

    Raises ValueError naming the problem when a question is unknown, answered or expired, or when
    a choice is not one of its options. "No project" is applied at once (nothing to link).
    """
    moment, cutoff = now or utcnow(), _cutoff(now)
    with Session(engine) as session:
        rows: list[tuple[FilingQuestion, str]] = []
        for question_id, choice in answers:
            row = session.get(FilingQuestion, question_id)
            if row is None or row.answer is not None or as_utc(row.asked_at) < cutoff:
                raise ValueError(f"Question {question_id} is no longer open.")
            match = next((o for o in _options(row) if o.casefold() == str(choice).casefold()), None)
            if match is None:
                raise ValueError(f"The answer to question {question_id} is not one of the choices.")
            rows.append((row, match))
        for row, match in rows:
            row.answer, row.answered_at = match, moment
            row.applied_at = moment if match == NO_PROJECT else None
            session.add(row)
        session.commit()
    return {"answered": len(rows)}


def answered_unapplied(engine: Engine) -> list[dict]:
    """Project answers a run still has to apply: {"question_id", "item_id", "project", "note_path"}."""
    with Session(engine) as session:
        rows = session.exec(select(FilingQuestion).where(
            FilingQuestion.answer.is_not(None), FilingQuestion.applied_at.is_(None))
            .order_by(FilingQuestion.answered_at, FilingQuestion.id)).all()
        out = []
        for row in rows:
            filed = filed_entry(session, row.item_id)
            out.append({"question_id": row.id, "item_id": row.item_id, "project": row.answer,
                        "note_path": filed["path"] if filed else None})
        return out


def mark_applied(engine: Engine, item_id: int, *, now: datetime | None = None) -> dict:
    """Record that a run linked the item to the answered project; the filed entry gets the project.

    Returns {"applied", "item_id", "project"}, or the error "nothing_to_apply".
    """
    with Session(engine) as session:
        row = session.exec(select(FilingQuestion).where(
            FilingQuestion.item_id == item_id, FilingQuestion.answer.is_not(None),
            FilingQuestion.applied_at.is_(None))).first()
        if row is None:
            return _error("nothing_to_apply", "This item has no answered question to apply.")
        row.applied_at = now or utcnow()
        session.add(row)
        extra = session.exec(select(ItemExtra).where(ItemExtra.item_id == item_id)).first()
        data = loads(extra.data, {}) if extra else {}
        filed = data.get("filed") if isinstance(data, dict) else None
        if extra is not None and isinstance(filed, dict):
            extra.data = dumps({**data, "filed": {**filed, "project": row.answer}})
            session.add(extra)
        session.commit()
        return {"applied": True, "item_id": item_id, "project": row.answer}


def expire_questions(engine: Engine, *, now: datetime | None = None) -> int:
    """Delete unanswered questions older than 14 days; returns how many went."""
    cutoff = _cutoff(now)
    with Session(engine) as session:
        old = [r for r in session.exec(select(FilingQuestion).where(
            FilingQuestion.answer.is_(None))).all() if as_utc(r.asked_at) < cutoff]
        for row in old:
            session.delete(row)
        session.commit()
    if old:
        logger.info("removed %d unanswered filing questions after %d days", len(old), EXPIRE_DAYS)
    return len(old)
