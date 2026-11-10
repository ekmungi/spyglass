# src/spyglass_service/api_briefs.py
"""Daily Brief REST API: list briefs, read one, and manually generate the next."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from spyglass_service.brief import BriefComposeError, compose_due_briefs, recompose_brief
from spyglass_service.brief_time import days_to_compose, local_day_of
from spyglass_service.models import Brief

router = APIRouter(prefix="/api")


def _iso_utc(dt: datetime) -> str:
    """Serialize a stored datetime with an explicit UTC offset.

    SQLite hands back naive datetimes that are UTC by convention; a bare
    isoformat() of those is parsed as LOCAL time by JavaScript's Date, shifting
    every displayed window by the client's UTC offset. Attaching tzinfo makes
    the wire format unambiguous (+00:00).
    """
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).isoformat()


def _title(covers_until: datetime) -> str:
    """Human title for a brief, from its covers_until date (e.g. 'Daily Brief — Jul 2, 2026').

    Built from date parts with an f-string because strftime's no-pad day flag is
    platform-specific ('%-d' POSIX vs '%#d' Windows). This is the LEGACY
    title derivation, still used for briefs with no publish_day (see `_summary_title`).

    Args:
        covers_until: The brief's window end (naive or aware).

    Returns:
        The display title string.
    """
    return f"Daily Brief — {covers_until.strftime('%b')} {covers_until.day}, {covers_until.year}"


def _fmt_date(d: date) -> str:
    """Render a date the same way `_title` renders covers_until (e.g. 'Jul 3, 2026').

    Shared so the publish-day titles (`_summary_title`) match the legacy
    title's exact format; only the source of the date parts differs.

    Args:
        d: The date to render.

    Returns:
        The formatted date string, no leading zero on the day (platform-independent).
    """
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _summary_title(brief: Brief) -> str:
    """Derive the brief's display title.

    Three cases:
    - Legacy (publish_day == ''): brief predates publish-day windowing -- keep the
      EXISTING covers_until-based title untouched so old briefs don't change.
    - Digest (publish_day set, but covers_from/until fall on DIFFERENT local days):
      the brief folds an older tail of days into one bucket, so it reads as
      "Earlier — through <publish_day>" rather than claiming a single day.
    - Single day (publish_day set, covers_from/until on the SAME local day): plain
      "Daily Brief — <publish_day>", formatted from publish_day itself (not
      covers_until) so the title always matches the day the brief was bucketed on.

    Args:
        brief: A persisted Brief row.

    Returns:
        The display title string.
    """
    if not brief.publish_day:
        return _title(brief.covers_until)
    publish_date = date.fromisoformat(brief.publish_day)
    spans_multiple_days = local_day_of(brief.covers_from, None, None) != local_day_of(
        brief.covers_until, None, None
    )
    if spans_multiple_days:
        return f"Earlier — through {_fmt_date(publish_date)}"
    return f"Daily Brief — {_fmt_date(publish_date)}"


def _summary_dict(brief: Brief) -> dict:
    """The light list-row shape: metadata + title, no markdown body.

    Args:
        brief: A persisted Brief row.

    Returns:
        Dict with id, created_at, covers_from, covers_until, item_count, low_count,
        publish_day, reviewed, title.
    """
    return {
        "id": brief.id,
        "created_at": _iso_utc(brief.created_at),
        "covers_from": _iso_utc(brief.covers_from),
        "covers_until": _iso_utc(brief.covers_until),
        "item_count": brief.item_count,
        "low_count": brief.low_count,
        "publish_day": brief.publish_day,
        "reviewed": brief.reviewed,
        "title": _summary_title(brief),
    }


def _full_dict(brief: Brief) -> dict:
    """The detail shape: everything in the summary plus the markdown body.

    Args:
        brief: A persisted Brief row.

    Returns:
        The summary dict extended with the markdown field.
    """
    return {**_summary_dict(brief), "markdown": brief.markdown}


def _list_sort_key(brief: Brief) -> tuple[str, datetime, int]:
    """Coalesced sort key for the brief list: publish_day when set, else the
    local calendar day of created_at (as an ISO string, so the two keys compare directly
    against real publish_day strings) -- plus created_at and id as tiebreakers.

    A plain `order_by(publish_day)` would sort every legacy brief (publish_day == '')
    to the bottom regardless of when it was actually created, since '' is the lowest
    possible string. Falling back to created_at's local day instead slots a legacy
    brief where it chronologically belongs among dated (publish-day) briefs. Two briefs
    can share the same day bucket (e.g. two legacy briefs created the same day, before
    publish-day windowing existed), so created_at breaks the tie -- without it, Python's
    stable sort would leave same-day rows in their original (insertion) order instead of
    the newest-actually-created one first. created_at's wall-clock resolution can coincide
    across two fast successive inserts (observed on Windows), so `id` (autoincrement,
    strictly insertion-ordered) is the final, always-deterministic tiebreaker.

    Args:
        brief: A persisted Brief row.

    Returns:
        (day, created_at, id) tuple, all ascending-comparable (the caller reverses for
        newest-first). id defaults to 0 for an unpersisted row (should not occur here,
        but keeps the key total).
    """
    day = brief.publish_day if brief.publish_day else local_day_of(brief.created_at, None, None).isoformat()
    return (day, brief.created_at, brief.id or 0)


@router.get("/briefs")
def list_briefs(request: Request) -> list[dict]:
    """All briefs newest-first, without their markdown bodies (the tab's picker list).

    Sorted by the coalesced publish-day key (`_list_sort_key`) rather than a plain
    SQL order_by, since the coalesce-to-created_at-day fallback for legacy briefs
    isn't a pure column -- fetch then sort in Python (small table, simplest correct
    approach).
    """
    with Session(request.app.state.engine) as session:
        rows = list(session.exec(select(Brief)).all())
    rows.sort(key=_list_sort_key, reverse=True)
    return [_summary_dict(brief) for brief in rows]


@router.get("/briefs/{brief_id}")
def get_brief(request: Request, brief_id: int) -> dict:
    """One brief including its markdown; 404 for an unknown id."""
    with Session(request.app.state.engine) as session:
        brief = session.get(Brief, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="brief not found")
    return _full_dict(brief)


@router.post("/briefs/generate")
async def generate_brief(request: Request) -> dict:
    """Manually compose every due publish-day brief now.

    The compose makes LLM network calls, so it runs in the threadpool off the event loop.
    compose_due_briefs composes one brief per un-briefed publish-day (newest first, within
    the recency horizon, with no cap on the number of days) and pauses per day
    internally -- a day whose LLM call failed is simply absent from the returned list (it
    stays eligible for a later retry), so this endpoint no longer surfaces a global 503
    pause. The response lists each composed brief's light summary
    (publish_day/reviewed/title) plus `held`: how many due days did NOT compose this run
    (a heavy day the partition gate paused). `held` lets the UI say "1 day held" instead of
    the misleading "nothing to brief" -- compose returns [] both when nothing is due and
    when every due day paused, and the two mean very different things to the user.
    """
    engine = request.app.state.engine
    settings = request.app.state.settings
    index = request.app.state.service_state.ensure_index()
    gate = request.app.state.compose_gate

    # Compose under the single-writer gate, blocking behind any in-flight
    # background compose so a manual "generate now" can't race one into a double-composed
    # day. The due-day count and the compose run together inside the gate, so `held`
    # (expected minus composed) is measured against the same eligibility the compose saw:
    # each composed day stamps its cards (shrinking what's due), and a heavy day the
    # partition gate pauses stays counted as held rather than silently vanishing. Every un-briefed
    # day is its own brief, so expected is simply the due-day count.
    def _compose_under_gate() -> tuple[int, list[Brief]]:
        with gate.exclusive():
            expected = len(days_to_compose(engine, index, horizon_days=settings.brief_horizon_days))
            return expected, compose_due_briefs(engine, index, settings)

    expected, briefs = await run_in_threadpool(_compose_under_gate)
    # Clamp: a mocked/edge run can report more composed than expected; never go negative.
    held = max(0, expected - len(briefs))
    status = "composed" if briefs else "empty"
    return {
        "composed": [_summary_dict(brief) for brief in briefs],
        "status": status,
        "held": held,
    }


@router.post("/briefs/{brief_id}/recompose")
async def recompose(request: Request, brief_id: int) -> dict:
    """Rebuild an existing brief's narrative in place from its already-stamped cards.

    Membership never changes: the cards keep their stamp, only the markdown
    and the featured/listed split are recomputed from the current effective relevance.
    Runs in the threadpool (LLM network call). 404 for an unknown id; an LLM failure is
    a 503 {"status": "llm_unavailable"} and the stored brief stays untouched.
    """
    engine = request.app.state.engine
    settings = request.app.state.settings
    index = request.app.state.service_state.ensure_index()
    try:
        brief = await run_in_threadpool(recompose_brief, engine, index, settings, brief_id)
    except BriefComposeError as exc:
        raise HTTPException(status_code=503, detail={"status": "llm_unavailable"}) from exc
    if brief is None:
        raise HTTPException(status_code=404, detail="brief not found")
    return _full_dict(brief)
