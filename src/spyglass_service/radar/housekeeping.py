"""Weekly upkeep: trim what the reader never used, so the database and caches stay bounded.

`run_housekeeping` runs seven independent steps and reports what each removed:

1. Stored full text and reader documents of old items the reader never touched. The item, its
   judgement and its embedding stay, so the feed, the search and the "related" lists are unchanged;
   opening such an item later simply builds its reader document again.
2. Learning signals older than 400 days and run logs older than 90 days.
3. Daily briefs older than 400 days.
4. The PDF and image caches, trimmed to their size limits, least recently used first. Before that,
   pictures and PDFs the reader sent in that are still in a cache are moved to their own store
   (`from_you_store`), which is never trimmed; its size is part of the report.
5. Assistant threads that never got a message, after a week.
6. A report of the space the database could give back (and, when the database was created with
   incremental vacuum, a bounded amount of it is returned).

An item counts as touched, and is never cleaned, when the reader opened it, read it, saved it,
voted on it, hid it, wrote a note on it, sent it in, wrote it to the vault, asked the assistant
about it, or was shown it in any stored brief. A step that fails is reported and does not stop
the others.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, or_
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.radar import from_you_store
from spyglass_service.models import Content, Item, RunLog
from spyglass_service.radar.models import (
    AssistMessage,
    AssistThread,
    ItemState,
    RadarBrief,
    ReaderDoc,
    Signal,
    loads,
)

logger = logging.getLogger(__name__)

SIGNAL_DAYS = 400
RUN_LOG_DAYS = 90
BRIEF_DAYS = 400
EMPTY_THREAD_DAYS = 7
# Size limits of the on-disk caches. The PDF limit is the reader's own (imported when present).
PDF_CACHE_BYTES = 1024 ** 3
IMG_CACHE_BYTES = 256 * 1024 ** 2
# Pages handed back to the file per run: about 16 MB at the usual page size, so one run never
# holds the database for long.
VACUUM_PAGES = 4096
_BATCH = 500


def _naive(moment: datetime) -> datetime:
    """The UTC wall time without a zone, which is how the database stores times."""
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _brief_item_ids(session: Session) -> set[int]:
    """Every item id mentioned in any stored brief (stories and their sources)."""
    found: set[int] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key == "item_id" and isinstance(inner, int):
                    found.add(inner)
                else:
                    walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    for raw in session.exec(select(RadarBrief.doc)).all():
        walk(loads(raw, None))
    return found


def _touched_item_ids(session: Session) -> set[int]:
    """Ids of items the reader interacted with in any way."""
    state = select(ItemState.item_id).where(or_(
        ItemState.from_user.is_(True), ItemState.saved_at.is_not(None),  # type: ignore[attr-defined]
        ItemState.opened_at.is_not(None), ItemState.open_count > 0,  # type: ignore[attr-defined]
        ItemState.read_seconds > 0, ItemState.vote.is_not(None),  # type: ignore[attr-defined]
        ItemState.vault_path.is_not(None), ItemState.hidden.is_(True),  # type: ignore[attr-defined]
        ItemState.user_note.is_not(None)))  # type: ignore[attr-defined]
    touched = set(session.exec(state).all())
    touched |= {i for i in session.exec(select(Signal.item_id).distinct()).all() if i is not None}
    touched |= {i for i in session.exec(select(AssistThread.item_id).distinct()).all()
                if i is not None}
    return touched | _brief_item_ids(session)


def _trim_stored_text(engine: Engine, settings, now: datetime) -> dict:
    """Step 1: drop the reader document and stored text of old, untouched items."""
    days = int(getattr(settings, "radar_retention_days", 0) or 0)
    if days <= 0:
        return {"skipped": "retention is switched off"}
    cutoff = _naive(now) - timedelta(days=days)
    with Session(engine) as session:
        old = set(session.exec(select(Item.id).where(Item.fetched_at < cutoff)).all())
        readers = set(session.exec(select(ReaderDoc.item_id)).all())
        contents = set(session.exec(select(Content.item_id)).all())
        eligible = (old & (readers | contents)) - _touched_item_ids(session)
        ids = sorted(eligible)
        for start in range(0, len(ids), _BATCH):
            session.exec(delete(ReaderDoc).where(
                ReaderDoc.item_id.in_(ids[start:start + _BATCH])))  # type: ignore[attr-defined]
        session.commit()
    for item_id in ids:
        content_store.delete_content(engine, item_id)  # also removes the full-text index row
    return {"items": len(ids), "reader_docs": len(eligible & readers),
            "contents": len(eligible & contents)}


def _prune_history(engine: Engine, now: datetime) -> dict:
    """Step 2: old learning signals and run logs."""
    with Session(engine) as session:
        signals = session.exec(delete(Signal).where(
            Signal.at < _naive(now) - timedelta(days=SIGNAL_DAYS))).rowcount
        logs = session.exec(delete(RunLog).where(
            RunLog.started_at < _naive(now) - timedelta(days=RUN_LOG_DAYS))).rowcount
        session.commit()
    return {"signals": signals, "run_logs": logs}


def _prune_briefs(engine: Engine, now: datetime) -> dict:
    """Step 3: old daily briefs."""
    with Session(engine) as session:
        count = session.exec(delete(RadarBrief).where(
            RadarBrief.created_at < _naive(now) - timedelta(days=BRIEF_DAYS))).rowcount
        session.commit()
    return {"deleted": count}


def prune_folder(folder: Path, max_bytes: int) -> int:
    """Delete the least recently used files under `folder` until it fits in `max_bytes`.

    Returns the number of files removed. A missing folder is fine and a file that cannot be
    removed is skipped.
    """
    if not folder.is_dir():
        return 0
    entries = []
    for path in folder.rglob("*"):
        try:
            if path.is_file():
                info = path.stat()
                entries.append((info.st_mtime, info.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, path in sorted(entries):  # oldest first
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not remove %s: %s", path.name, type(exc).__name__)
            continue
        total -= size
        removed += 1
    return removed


def _keep_sent_files(engine: Engine, settings) -> dict:
    """Move the reader's own pictures and PDFs out of the caches; report how many and the store size.

    This runs before the caches are trimmed, so a file the reader sent in is never lost to the trim.
    """
    data_dir = Path(settings.data_dir)
    moved = from_you_store.move_from_caches(engine, data_dir)
    return {**moved, "stored_bytes": from_you_store.size_bytes(data_dir)}


def _prune_caches(settings) -> dict:
    """Step 4: trim the PDF and image caches."""
    data_dir = Path(settings.data_dir)
    try:
        from spyglass_service.radar.reader.pdf import MAX_CACHE_BYTES as pdf_limit
    except ImportError:
        pdf_limit = PDF_CACHE_BYTES
    return {"pdf_cache": prune_folder(data_dir / "pdf_cache", min(PDF_CACHE_BYTES, pdf_limit)),
            "img_cache": prune_folder(data_dir / "img_cache", IMG_CACHE_BYTES)}


def _prune_threads(engine: Engine, now: datetime) -> dict:
    """Step 5: assistant threads that never received a message."""
    cutoff = _naive(now) - timedelta(days=EMPTY_THREAD_DAYS)
    with Session(engine) as session:
        has_message = select(AssistMessage.thread_id).distinct()
        count = session.exec(delete(AssistThread).where(
            AssistThread.created_at < cutoff,
            AssistThread.id.not_in(has_message))).rowcount  # type: ignore[union-attr]
        session.commit()
    return {"deleted": count}


def compact_database(engine: Engine, *, pages: int = VACUUM_PAGES) -> dict:
    """Step 6: report the reclaimable space and give a bounded part of it back when possible.

    Returning space needs a database created with incremental vacuum; for any other database the
    free pages are only reported (a full VACUUM would block every other use of the file).
    """
    modes = {0: "none", 1: "full", 2: "incremental"}
    with engine.connect() as conn:
        mode = int(conn.exec_driver_sql("PRAGMA auto_vacuum").scalar() or 0)
        page_size = int(conn.exec_driver_sql("PRAGMA page_size").scalar() or 0)
        free = int(conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0)
        reclaimed = 0
        if mode == 2 and free:
            step = max(1, int(min(free, pages)))  # an int, so safe to put in the statement
            conn.exec_driver_sql(f"PRAGMA incremental_vacuum({step})")
            conn.commit()
            reclaimed = (free - int(conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0)) \
                * page_size
        remaining = int(conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0) * page_size
    return {"auto_vacuum": modes.get(mode, "none"), "reclaimable_bytes": remaining,
            "reclaimed_bytes": reclaimed}


def run_housekeeping(engine: Engine, settings, *, now: datetime | None = None) -> dict:
    """Run every upkeep step and return what each did.

    The result has one entry per step (retention, history, briefs, from_you, caches, threads, database),
    each either a dict of counts or `{"error": "..."}`, and `ok` (False when any step failed).
    """
    moment = now or datetime.now(UTC)
    steps = {
        "retention": lambda: _trim_stored_text(engine, settings, moment),
        "history": lambda: _prune_history(engine, moment),
        "briefs": lambda: _prune_briefs(engine, moment),
        "from_you": lambda: _keep_sent_files(engine, settings),
        "caches": lambda: _prune_caches(settings),
        "threads": lambda: _prune_threads(engine, moment),
        "database": lambda: compact_database(engine),
    }
    report: dict = {}
    for name, step in steps.items():
        try:
            report[name] = step()
        except Exception as exc:  # noqa: BLE001 -- one failed step must not stop the others
            logger.exception("housekeeping step %s failed", name)
            report[name] = {"error": f"{type(exc).__name__}: {exc}"}
    report["ok"] = not any("error" in v for v in report.values() if isinstance(v, dict))
    logger.info("housekeeping finished: %s", report)
    return report
