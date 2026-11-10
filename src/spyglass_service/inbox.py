"""The paper inbox: papers the user shares in one Slack channel.

A Claude desktop session (the spyglass-inbox skill) reads the channel, files each paper in the
vault with a paper-filing skill, writes its debrief into that note, and reports to Spyglass
through these functions, which the MCP server wraps: start a run, add each paper, record it
filed, finish the run. Spyglass keeps one InboxRun per pass and one InboxEntry per shared
paper; the Inbox tab lists them. The watermark (the newest Slack message handled) moves only
when a run finishes cleanly, so a failed run is simply retried; a paper already known gets a
second entry on the same card.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.api_pages import _ensure_card
from spyglass_service.models import Card, CardState, InboxEntry, InboxRun, Item
from spyglass_service.paper_match import canonical_paper_url, same_paper

# A run still "running" after this long was abandoned (the session was closed midway).
STALE_AFTER = timedelta(hours=2)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite hands datetimes back naive; they were stored as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _ts_key(ts: str) -> float:
    try:
        return float(ts)
    except ValueError:
        return float("-inf")


def last_watermark(engine: Engine) -> str | None:
    """The newest Slack message handled by any run that finished cleanly. The newest message, not
    the latest run: two overlapping runs finishing out of order must not move it back."""
    with Session(engine) as session:
        marks = session.exec(
            select(InboxRun.watermark).where(
                InboxRun.status == "ok", InboxRun.watermark.is_not(None)  # type: ignore[union-attr]
            )
        ).all()
    return max(marks, key=_ts_key) if marks else None


def start_run(engine: Engine) -> dict:
    """Open a run; `since` is where the session starts reading the channel (None: from the start)."""
    with Session(engine) as session:
        run = InboxRun()
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id
    return {"run_id": run_id, "since": last_watermark(engine)}


def add_paper(
    engine: Engine,
    run_id: int | None,
    url: str,
    message_text: str | None = None,
    message_ts: str | None = None,
    title: str | None = None,
) -> dict:
    """Record a shared paper: reuse the card it already has (from a feed or an earlier share) or
    create one, and add an entry for this share. A retried run that meets the same Slack message
    again reuses its entry. Returns card_id, entry_id and already_known (shared before in another
    message), or an error dict for a link that is not http(s) or an unknown run."""
    if urlsplit(url.strip()).scheme not in ("http", "https"):
        return {"error": "bad_url", "detail": "only http and https links can be filed"}
    canonical = canonical_paper_url(url)
    with Session(engine) as session:
        run = session.get(InboxRun, run_id) if run_id is not None else None
        if run_id is not None and run is None:
            return {"error": "not_found", "detail": f"no inbox run {run_id}"}
        item = same_paper(session, url, canonical)
        if item is None:
            item = Item(
                source="inbox", external_id=canonical, title=title or url, url=url,
                summary=message_text, origin="Slack",
            )
            session.add(item)
            session.commit()
            session.refresh(item)
        card = _ensure_card(session, item)
        entries = session.exec(select(InboxEntry).where(InboxEntry.card_id == card.id)).all()
        entry = next((e for e in entries if message_ts and e.message_ts == message_ts), None)
        known = any(e is not entry for e in entries)
        if entry is None:
            entry = InboxEntry(card_id=card.id, message_ts=message_ts, message_text=message_text)
        if entry.run_id != run_id or entry.id is None:
            entry.run_id = run_id
            if run is not None:
                run.papers += 1
                session.add(run)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return {"card_id": card.id, "entry_id": entry.id, "already_known": known}


def file_paper(
    engine: Engine,
    entry_id: int,
    title: str | None = None,
    summary: str = "",
    note_path: str | None = None,
    full_text: bool = False,
    vault: Path | None = None,
) -> dict | None:
    """Record that a paper is filed: its vault note (where the debrief lives) and a short summary.
    A vault-relative note path is stored absolute, as briefings are. A title replaces the
    placeholder only on cards the inbox created. None for an unknown entry."""
    if note_path and vault is not None and not Path(note_path).is_absolute():
        note_path = str(vault / note_path)
    with Session(engine) as session:
        entry = session.get(InboxEntry, entry_id)
        card = session.get(Card, entry.card_id) if entry else None
        if entry is None or card is None:
            return None
        item = session.get(Item, card.item_id)
        if title and item is not None and item.source == "inbox":
            item.title = title
            session.add(item)
        if summary:
            card.summary = summary
            card.curated = True
        if note_path:
            card.briefing_path = note_path
            card.state = CardState.FINISHED
        card.updated_at = _now()
        entry.filed = True
        entry.full_text = full_text
        session.add_all([card, entry])
        session.commit()
        return {"card_id": card.id}


def finish_run(
    engine: Engine, run_id: int, ok: bool, watermark: str | None = None, error: str | None = None
) -> dict | None:
    """Close a run. Only a clean run moves the watermark. None for an unknown run."""
    with Session(engine) as session:
        run = session.get(InboxRun, run_id)
        if run is None:
            return None
        run.status = "ok" if ok else "error"
        run.watermark = watermark if ok else None
        run.error = None if ok else (error or "The run reported a failure without a reason.")
        run.finished_at = _now()
        session.add(run)
        session.commit()
        return {"run_id": run_id, "status": run.status}


def _run_out(run: InboxRun) -> dict:
    status, error = run.status, run.error
    if status == "running" and _now() - _aware(run.started_at) > STALE_AFTER:
        status = "error"
        error = "The run did not finish (the Claude session may have been closed)."
    return {
        "id": run.id, "status": status, "papers": run.papers, "error": error,
        "debrief_path": run.debrief_path,
        "started_at": _aware(run.started_at).isoformat(),
        "finished_at": _aware(run.finished_at).isoformat() if run.finished_at else None,
    }


def inbox_view(engine: Engine, channel: str, limit: int = 100) -> dict:
    """What the Inbox tab shows: the channel, the latest run and the shared papers, newest first."""
    with Session(engine) as session:
        run = session.exec(
            select(InboxRun).order_by(InboxRun.started_at.desc())  # type: ignore[union-attr]
        ).first()
        shared = dict(
            session.exec(select(InboxEntry.card_id, func.count()).group_by(InboxEntry.card_id)).all()
        )
        rows = session.exec(
            select(InboxEntry, Card, Item)
            .join(Card, Card.id == InboxEntry.card_id)
            .join(Item, Item.id == Card.item_id)
            .order_by(InboxEntry.added_at.desc(), InboxEntry.id.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
        papers = [
            {
                "entry_id": entry.id, "card_id": card.id, "title": item.title, "url": item.url,
                "summary": card.summary or "", "note_path": card.briefing_path,
                "message_text": entry.message_text, "full_text": entry.full_text,
                "filed": entry.filed, "shared": shared.get(card.id, 1),
                "added_at": _aware(entry.added_at).isoformat(),
            }
            for entry, card, item in rows
        ]
        return {"channel": channel, "last_run": _run_out(run) if run else None, "papers": papers}
