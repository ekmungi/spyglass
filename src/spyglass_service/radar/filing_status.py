"""What the background filing run did last, kept in one stored document (RadarDoc "filing_run").

A run begins with a random token (`begin_run`); the request the session starts with carries it,
and the run-only tools (`radar_filing_report`, `radar_filing_ask`, `radar_filing_propose`) are
accepted only with the token of the run in progress, so no other session can speak for a run. A
run ends `ok`, `partial` (it ran, but some of its items are still waiting) or `stopped` with a
reason code; after `partial` or `stopped` the next attempt waits longer each time (30 minutes,
doubling, at most a day), or until a usage limit resets. A run left "running" by a crash is closed
as stopped when the service next looks (`recover_crashed`).
"""

import logging
import re
import secrets
import threading
from datetime import datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.radar.filing_tables import plain_line
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow

logger = logging.getLogger(__name__)

DOC_KEY = "filing_run"
MODES = ("off", "auto", "plan_first")
KINDS = ("file", "plan")
RESULTS = ("ok", "partial", "stopped")
# Why a run stopped, as the status line and the brief say it.
STOP_REASONS = {
    "skills_missing": "The vault skills were not available to the run",
    "tools_missing": "The Spyglass or Obsidian tools were not available to the run",
    "obsidian_unreachable": "Obsidian was closed",
    "not_signed_in": "Claude Code is not signed in",
    "usage_limit": "Your Claude usage limit was reached",
    "time_limit": "The run took too long and was stopped",
    "no_vault": "No vault folder is set",
    "claude_missing": "The claude command was not found",
    "crashed": "Spyglass stopped while the run was going",
    "failed": "The run failed",
}
# The reasons a session may give itself through radar_filing_report.
REPORTABLE = ("skills_missing", "tools_missing", "obsidian_unreachable", "failed")
REPORT_STATUSES = ("done", "stopped")
RETRY_FIRST = timedelta(minutes=30)
RETRY_MAX = timedelta(hours=24)
DETAIL_MAX = 300
REFUSED_MAX = 20
_TOKEN = re.compile(r"[0-9a-f]{16}")
_lock = threading.Lock()

_EMPTY = {
    "state": "idle", "run_id": None, "mode": None, "kind": None, "model": None,
    "started_at": None, "finished_at": None, "item_ids": [], "result": None, "reason": None,
    "detail": None, "filed": 0, "asked": 0, "proposed": 0, "cost_usd": None, "duration_ms": None,
    "failures": 0, "next_retry": None, "last_ran_at": None, "report": None, "refused": [],
}


def _load(session: Session) -> dict:
    """The stored document merged over the defaults."""
    row = session.get(RadarDoc, DOC_KEY)
    stored = loads(row.body if row else None, {})
    return {**_EMPTY, **(stored if isinstance(stored, dict) else {})}


def _save(session: Session, status: dict) -> dict:
    """Store the document and return it."""
    row = session.get(RadarDoc, DOC_KEY) or RadarDoc(key=DOC_KEY, body="{}")
    row.body = dumps(status)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return status


def read_status(engine: Engine) -> dict:
    """The current status document (defaults when no run ever started)."""
    with Session(engine) as session:
        return _load(session)


def reason_text(code: str | None) -> str:
    """The plain sentence for a stop reason (unknown codes read as "The run failed")."""
    return STOP_REASONS.get(code or "", STOP_REASONS["failed"])


def retry_delay(failures: int) -> timedelta:
    """How long to wait after the `failures`-th stop in a row: 30 minutes doubling, at most a day."""
    if failures <= 0:
        return timedelta(0)
    return min(RETRY_FIRST * (2 ** min(failures - 1, 10)), RETRY_MAX)


def begin_run(engine: Engine, *, mode: str, kind: str, model: str, item_ids: list[int],
              now: datetime | None = None) -> dict:
    """Mark a run as started and return the status, which holds the run's new token."""
    if mode not in MODES[1:] or kind not in KINDS:
        raise ValueError("unknown filing mode or run kind")
    with _lock, Session(engine) as session:
        status = _load(session)
        status.update(state="running", run_id=secrets.token_hex(8), mode=mode, kind=kind,
                      model=model, started_at=(now or utcnow()).isoformat(), finished_at=None,
                      item_ids=list(item_ids), result=None, reason=None, detail=None, filed=0,
                      asked=0, proposed=0, cost_usd=None, duration_ms=None, report=None)
        return _save(session, status)


def current_run(engine: Engine, run_id: object) -> dict | None:
    """The status of the run in progress when `run_id` is its token, else None."""
    if not isinstance(run_id, str) or not _TOKEN.fullmatch(run_id):
        return None
    status = read_status(engine)
    if status["state"] != "running" or not status["run_id"]:
        return None
    return status if secrets.compare_digest(status["run_id"], run_id) else None


def record_report(engine: Engine, run_id: object, status: object, reason: object,
                  detail: object) -> dict:
    """Keep what the session says about how it ended; returns {"reported": True} or an error."""
    if status not in REPORT_STATUSES or (reason is not None and reason not in REPORTABLE):
        return {"error": "invalid_report",
                "detail": f"status is one of {REPORT_STATUSES}; reason is one of {REPORTABLE}."}
    with _lock, Session(engine) as session:
        current = _load(session)
        if current["state"] != "running" or current["run_id"] != run_id:
            return {"error": "not_running", "detail": "That run is not in progress."}
        current["report"] = {"status": status, "reason": reason,
                             "detail": plain_line(detail, DETAIL_MAX)}
        _save(session, current)
    return {"reported": True}


def finish_run(engine: Engine, run_id: str, *, result: str, reason: str | None = None,
               detail: str | None = None, filed: int = 0, asked: int = 0, proposed: int = 0,
               cost_usd: float | None = None, duration_ms: int | None = None,
               retry_at: datetime | None = None, refused: list[str] | None = None,
               now: datetime | None = None) -> dict:
    """Close the run: its result, counts, cost and refused tool calls (at most 20); a stop or a
    partial run sets the next retry."""
    if result not in RESULTS:
        raise ValueError("unknown run result")
    moment = now or utcnow()
    with _lock, Session(engine) as session:
        status = _load(session)
        if status["run_id"] != run_id:
            logger.warning("finishing a filing run that is no longer the current one")
        failures = 0 if result == "ok" else int(status["failures"]) + 1
        retry = None if result == "ok" else (retry_at or moment + retry_delay(failures))
        status.update(state="idle", finished_at=moment.isoformat(), result=result,
                      reason=reason if result == "stopped" else None,
                      detail=plain_line(detail, DETAIL_MAX) or None, filed=filed, asked=asked,
                      proposed=proposed, cost_usd=cost_usd, duration_ms=duration_ms,
                      failures=failures, next_retry=retry.isoformat() if retry else None,
                      refused=[plain_line(r, 200) for r in (refused or [])[:REFUSED_MAX]])
        if result != "stopped":
            status["last_ran_at"] = moment.isoformat()
        return _save(session, status)


def recover_crashed(engine: Engine, *, now: datetime | None = None) -> bool:
    """Close a run the service left "running" (it stopped meanwhile); True when one was closed."""
    status = read_status(engine)
    if status["state"] != "running":
        return False
    logger.warning("closing a filing run that was left running by a stopped service")
    finish_run(engine, status["run_id"], result="stopped", reason="crashed", now=now)
    return True
