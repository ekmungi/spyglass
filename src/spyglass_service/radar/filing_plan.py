"""The "show me the plan first" mode: one proposal per queued item, approved in one table.

A planning run writes nothing into the vault. For each queued item it calls
`radar_filing_propose`: what the item would become, the folder, the note's name, the project if
any, and whether it is unsure and why. Spyglass shows the rows as one table; the reader strikes
rows and presses Approve once (`decide`). Approved rows are filed by the next run; a struck row
leaves the plan and the queue. Every text a run sends is cleaned to one plain line before it is
stored, because the interface shows it.
"""

import logging
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.filed import vault_relative_parts
from spyglass_service.radar.filing_queue import FilingRow
from spyglass_service.radar.filing_tables import FilingProposal, as_utc, plain_line
from spyglass_service.radar.models import utcnow
from spyglass_service.radar.projects import project_directory

logger = logging.getLogger(__name__)

BECOMES_MAX, PLACE_MAX, NAME_MAX, PROJECT_MAX, REASON_MAX = 80, 300, 160, 80, 300
PENDING, APPROVED = "pending", "approved"


def _error(code: str, detail: str) -> dict:
    """A tool error payload."""
    return {"error": code, "detail": detail}


def _project(session: Session, settings, chosen: str | None, given: object) -> str | dict | None:
    """The project the row carries: the reader's choice when there is one, else a listed name.

    Returns the name, None for no project, or an error payload.
    """
    name = plain_line(given, PROJECT_MAX + 1) if isinstance(given, str) else ""
    if chosen:
        if name and name.casefold() != chosen.casefold():
            return _error("project_chosen", f"The reader chose the project \"{chosen}\" for this "
                                            "item; the plan must follow it.")
        return chosen
    if not name:
        return None
    for entry in project_directory(session, settings):
        if entry["name"].casefold() == name.casefold():
            return entry["name"]
    return _error("unknown_project", "Name one of the reader's listed projects, or none.")


def propose(engine: Engine, settings, item_id: int, *, becomes: object, place: object,
            name: object, project: object = None, unsure: bool = False, reason: object = "",
            now: datetime | None = None) -> dict:
    """Store (or replace) the plan row for a queued item; returns {"proposed", "item_id"} or an error.

    Errors: "not_queued", "invalid_proposal" (no kind of note or no name), "invalid_place" (not a
    folder path inside the vault), "project_chosen" (differs from the reader's choice) and
    "unknown_project".
    """
    parts = vault_relative_parts(place)
    clean_becomes, clean_name = plain_line(becomes, BECOMES_MAX), plain_line(name, NAME_MAX)
    with Session(engine) as session:
        if session.get(Item, item_id) is None:
            return _error("not_found", f"No Spyglass item {item_id}.")
        row = session.exec(select(FilingRow).where(FilingRow.item_id == item_id)).first()
        if row is None:
            return _error("not_queued", "Only items in the filing queue can be planned.")
        if not clean_becomes or not clean_name:
            return _error("invalid_proposal", "Say what the item becomes and the note's name.")
        if parts is None:
            return _error("invalid_place", "Give the folder relative to the vault, without '..'.")
        chosen = _project(session, settings, row.project, project)
        if isinstance(chosen, dict):
            return chosen
        proposal = session.exec(select(FilingProposal).where(
            FilingProposal.item_id == item_id)).first() or FilingProposal(item_id=item_id)
        proposal.becomes, proposal.name, proposal.project = clean_becomes, clean_name, chosen
        proposal.place = plain_line("/".join(parts), PLACE_MAX)
        proposal.unsure = bool(unsure)
        proposal.reason = plain_line(reason, REASON_MAX)
        proposal.proposed_at, proposal.decision, proposal.decided_at = now or utcnow(), PENDING, None
        session.add(proposal)
        session.commit()
    return {"proposed": True, "item_id": item_id}


def _row(p: FilingProposal) -> dict:
    """One plan row as the interface and the run see it."""
    return {"id": p.id, "item_id": p.item_id, "becomes": p.becomes, "place": p.place,
            "name": p.name, "project": p.project, "unsure": p.unsure, "reason": p.reason,
            "decision": p.decision, "proposed_at": as_utc(p.proposed_at).isoformat()}


def plan_rows(engine: Engine) -> list[dict]:
    """Every plan row of a queued item (pending and approved), in queue order."""
    with Session(engine) as session:
        rows = session.exec(select(FilingProposal).join(
            FilingRow, FilingRow.item_id == FilingProposal.item_id)
            .order_by(FilingRow.requested_at, FilingRow.id)).all()
        return [_row(p) for p in rows]


def approved_rows(engine: Engine) -> list[dict]:
    """The approved rows a filing run must carry out, in queue order."""
    return [r for r in plan_rows(engine) if r["decision"] == APPROVED]


def unplanned_ids(engine: Engine) -> list[int]:
    """Queued items that have no plan row yet, in queue order."""
    with Session(engine) as session:
        planned = set(session.exec(select(FilingProposal.item_id)).all())
        rows = session.exec(select(FilingRow).order_by(FilingRow.requested_at, FilingRow.id)).all()
        return [r.item_id for r in rows if r.item_id not in planned]


def decide(engine: Engine, *, approved: list[int], struck: list[int],
           now: datetime | None = None) -> dict:
    """Apply the reader's one Approve: approved rows wait for the next run, struck rows leave the
    plan and the queue. All or nothing; returns {"approved", "struck"}.

    Raises ValueError when a row is named twice or is not a pending row any more.
    """
    if set(approved) & set(struck):
        raise ValueError("A row cannot be both approved and struck.")
    moment = now or utcnow()
    with Session(engine) as session:
        found = {}
        for proposal_id in [*approved, *struck]:
            proposal = session.get(FilingProposal, proposal_id)
            if proposal is None or proposal.decision != PENDING:
                raise ValueError(f"Plan row {proposal_id} is no longer waiting for a decision.")
            found[proposal_id] = proposal
        for proposal_id in approved:
            found[proposal_id].decision, found[proposal_id].decided_at = APPROVED, moment
            session.add(found[proposal_id])
        for proposal_id in struck:
            item_id = found[proposal_id].item_id
            session.delete(found[proposal_id])
            for queued in session.exec(select(FilingRow).where(FilingRow.item_id == item_id)).all():
                session.delete(queued)
        session.commit()
    return {"approved": len(approved), "struck": len(struck)}


def last_decision_at(engine: Engine) -> datetime | None:
    """When the reader last approved a plan (for the quiet-period rule), or None."""
    with Session(engine) as session:
        times = session.exec(select(FilingProposal.decided_at).where(
            FilingProposal.decided_at.is_not(None))).all()
    values = [as_utc(t) for t in times if t is not None]
    return max(values) if values else None
