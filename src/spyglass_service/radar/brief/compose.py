"""Compose a day's brief: pick candidates, group them into stories, fill sections, store it.

The selection is deterministic code (see `candidates`, `cluster` and `rank`). The one model
call writes the two-sentence opening and has a fallback, so `compose_brief` does not fail on a
model error. Composes are serialised within the process, so a scheduled brief and a "generate
now" for the same day never collide on the one-brief-per-day rule.
"""

import logging
import threading
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Item
from spyglass_service.radar.brief.candidates import CANDIDATE_WINDOW, load_candidates, unjudged_ids
from spyglass_service.radar.brief.cluster import cluster_candidates
from spyglass_service.radar.brief.document import build_document, story_item_ids
from spyglass_service.radar.brief.llm import LlmFn, make_llm
from spyglass_service.radar.brief.rank import build_sections
from spyglass_service.radar.models import RadarBrief, dumps, loads
from spyglass_service.radar.profile import get_profile, section_keys
from spyglass_service.radar.serialize import radar_items

logger = logging.getLogger(__name__)

# "From you" lists items the reader sent in since the previous brief's cut-off. With no
# previous brief it looks back this far only, because older bookmarks were imported in bulk.
FROM_USER_FIRST_WINDOW = timedelta(days=3)
# The very first brief shows at most this many "From you" items, newest first.
FROM_USER_FIRST_CAP = 10
# An item shown in any of this many previous briefs is never shown again.
NO_REPEAT_BRIEFS = 14
# "Collected" counts items fetched since the previous brief, or this long when there is none.
DEFAULT_COLLECTED_WINDOW = timedelta(hours=36)

# One compose at a time in this process (the scheduler and the "generate now" endpoint).
_COMPOSE_LOCK = threading.Lock()


def brief_tz(settings) -> tzinfo | None:
    """The configured IANA zone, or None (the machine's own zone) when unset or unknown."""
    name = getattr(settings, "radar_timezone", "") or ""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("Unknown radar_timezone %r; using the machine's time zone", name)
        return None


def _to_naive_utc(dt: datetime) -> datetime:
    """A naive-UTC copy of dt (naive input is taken as UTC, matching the database)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def local_today(settings, now: datetime | None = None) -> date:
    """Today's date in the brief's time zone."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(brief_tz(settings)).date()


def _end_of_day_utc(day: date, tz: tzinfo | None) -> datetime:
    """Naive-UTC instant at which the local calendar day ends."""
    midnight = datetime.combine(day + timedelta(days=1), time.min)
    local = midnight.replace(tzinfo=tz) if tz else midnight.astimezone()
    return _to_naive_utc(local)


def briefed_item_ids(session: Session, day: str, lookback: int = NO_REPEAT_BRIEFS) -> set[int]:
    """Item ids shown in the `lookback` briefs before `day` (leads and every named source)."""
    rows = session.exec(
        select(RadarBrief).where(RadarBrief.day < day).order_by(RadarBrief.day.desc()).limit(lookback)
    ).all()
    ids: set[int] = set()
    for row in rows:
        ids |= story_item_ids(loads(row.doc, {}) or {})
    return ids


def _previous_brief(session: Session, day: str) -> RadarBrief | None:
    """The most recent brief made for a day before `day`, or None."""
    return session.exec(
        select(RadarBrief).where(RadarBrief.day < day).order_by(RadarBrief.day.desc()).limit(1)
    ).first()


def _cutoff(brief: RadarBrief, tz: tzinfo | None) -> datetime:
    """The newest instant a stored brief could include: its first composition, or the end of its
    day when it was composed after the day was over. Regenerations do not move it."""
    return min(_to_naive_utc(brief.created_at), _end_of_day_utc(date.fromisoformat(brief.day), tz))


def _collected_since(previous: RadarBrief | None, ref: datetime, tz: tzinfo | None) -> datetime:
    """Start of the "collected" window: the previous brief's cut-off (or the last 36 hours)."""
    since = _cutoff(previous, tz) if previous else ref - DEFAULT_COLLECTED_WINDOW
    return max(since, ref - CANDIDATE_WINDOW)  # an old gap must not inflate the count


def _target_day(settings, day: str | date | None, moment: datetime) -> date:
    """The local day to compose; raises ValueError for an impossible date or a future day."""
    today = local_today(settings, moment)
    target = day if isinstance(day, date) else (date.fromisoformat(day) if day else today)
    if target > today:
        raise ValueError(f"{target.isoformat()} is in the future; the latest day is {today.isoformat()}")
    return target


def _store(session: Session, day_text: str, doc: dict, collected: int, moment: datetime) -> int:
    """Insert or replace the day's brief row; returns the number of stories shown.

    The first composition time is kept; a later compose only sets `regenerated_at`.
    """
    shown = sum(len(s["stories"]) for s in doc["sections"])
    row = session.exec(select(RadarBrief).where(RadarBrief.day == day_text)).first()
    if row is None:
        row = RadarBrief(day=day_text, doc="", created_at=_to_naive_utc(moment))
    else:
        row.regenerated_at = _to_naive_utc(moment)
    row.doc, row.story_count = dumps(doc), shown
    row.collected_count, row.read_minutes = collected, doc["read_minutes"]
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Another process stored this day between our read and commit: update its row instead.
        session.rollback()
        row = session.exec(select(RadarBrief).where(RadarBrief.day == day_text)).one()
        row.doc, row.story_count, row.regenerated_at = dumps(doc), shown, _to_naive_utc(moment)
        row.collected_count, row.read_minutes = collected, doc["read_minutes"]
        session.add(row)
        session.commit()
    return shown


def compose_brief(
    engine: Engine,
    settings,
    index: EmbeddingIndex | None,
    day: str | date | None = None,
    *,
    llm: LlmFn | None = None,
    now: datetime | None = None,
) -> dict:
    """Build and store the brief for a local day (today by default); returns the document.

    index: used to merge near-duplicate stories by embedding; None skips that step.
    llm: `(messages, schema) -> dict` for the opening; defaults to the configured writer model,
        and when there is no key or the call fails the opening is a plain sentence instead.
    now: the current instant (aware UTC or naive UTC); only tests pass it.
    Raises ValueError for a day that is not a date or is later than the local today.
    """
    moment = now or datetime.now(UTC)
    tz = brief_tz(settings)
    target = _target_day(settings, day, moment)
    day_text = target.isoformat()
    ref = min(_to_naive_utc(moment), _end_of_day_utc(target, tz))
    writer = llm if llm is not None else make_llm(settings, "brief_opening")
    with _COMPOSE_LOCK, Session(engine) as session:
        previous = _previous_brief(session, day_text)
        mine_since = _cutoff(previous, tz) if previous else ref - FROM_USER_FIRST_WINDOW
        candidates = load_candidates(
            session, ref, briefed_item_ids(session, day_text), mine_since,
            None if previous else FROM_USER_FIRST_CAP,
        )
        vectors = index.matrix_for([c.item_id for c in candidates]) if index is not None else None
        stories = cluster_candidates(candidates, vectors)
        since = _collected_since(previous, ref, tz)
        unjudged = unjudged_ids(session, since, ref)
        plans, quiet = build_sections(stories, ref, unjudged=len(unjudged),
                                      profile_sections=frozenset(section_keys(get_profile(session))))
        wanted = [m.item_id for p in plans for s in p.stories for m in s.members]
        items = {i["id"]: i for i in radar_items(session, wanted)}
        collected = int(session.exec(
            select(func.count(Item.id)).where(Item.fetched_at > since, Item.fetched_at <= ref)
        ).one())
        doc = build_document(day_text, moment, plans, items, quiet=quiet, collected=collected,
                             llm=writer, unjudged=unjudged)
        shown = _store(session, day_text, doc, collected, moment)
    logger.info("Composed brief %s: %d stories from %d candidates", day_text, shown, len(candidates))
    return doc
