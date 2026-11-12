"""The assessment pipeline: triage new items, digest the ones worth reading, mark reader items.

`run_pipeline` is what the scheduler and the "collect now" button call after new items land.
It triages every recent item without an assessment (newest first), then digests items over the
gate and every item the reader sent in, a few at a time in parallel. Each item is committed on
its own, so a crash or an unreachable model loses nothing that was already judged.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, and_, func
from sqlmodel import Session, or_, select

from spyglass_service.models import Card, Feed, InboxEntry, Item
from spyglass_service.radar.assess import (
    FetchFn,
    Judge,
    LlmFn,
    TRIAGE_BATCH,
    LlmUnavailable,
    digest_one,
    from_user_ids,
    make_judge,
    store_assessment,
    triage_fields,
    triage_rows,
)
from spyglass_service.radar.assess_attempts import (
    FAILED_STAGE,
    MAX_DIGEST_ATTEMPTS,
    MAX_TRIAGE_ATTEMPTS,
    convert_legacy_failures,
    record_triage_failure,
)
from spyglass_service.radar.assess_prompt import tier_for, triage_row
from spyglass_service.radar.models import Assessment, ItemState, utcnow

logger = logging.getLogger(__name__)

# Returns True when the run should end early (the service is shutting down).
StopFn = Callable[[], bool]
# Marks a digest that was skipped because a stop was requested before it started.
_STOPPED = object()

# Parallel digests: each one fetches a page and makes one model call, so a few at a time keeps
# the run quick without hammering sites or the model provider.
DIGEST_WORKERS = 4
# Without an explicit `since`, only items collected this recently are judged: the radar is about
# what is new, and the database holds thousands of old items nobody should pay to re-judge.
DEFAULT_WINDOW = timedelta(days=7)
# Items the reader sent in stay eligible longer, since they asked for them.
FROM_USER_WINDOW = timedelta(days=30)
# One run's cap; large enough to clear a full day's collection in one cycle.
DEFAULT_LIMIT = 600


def _naive_utc(value: datetime | None) -> datetime | None:
    """`value` as naive UTC, the form SQLite stores timestamps in."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _newest_first():
    """Ordering expression: publish time when known, else collection time, newest first."""
    return func.coalesce(Item.published_at, Item.fetched_at).desc()


def _reader_sent():
    """Subquery: ids of items the reader sent in."""
    return select(ItemState.item_id).where(ItemState.from_user == True)  # noqa: E712


def _keep_condition():
    """Items not from a switched-off feed, plus anything the reader sent in."""
    disabled = select(Feed.feed_url).where(Feed.enabled == False)  # noqa: E712
    return or_(Item.feed_url.is_(None), Item.feed_url.not_in(disabled), Item.id.in_(_reader_sent()))


def _reader_sent_since(moment: datetime):
    """Subquery: ids of items the reader sent in at or after `moment`.

    Measured by the capture time, so an old item the reader sends in today is judged; rows
    from before the capture time was recorded fall back to the item's collection time.
    """
    sent = func.coalesce(ItemState.captured_at, select(Item.fetched_at)
                         .where(Item.id == ItemState.item_id).scalar_subquery())
    return select(ItemState.item_id).where(ItemState.from_user == True, sent >= moment)  # noqa: E712


def _window(since: datetime | None, now: datetime | None):
    """Which items a run may look at, by collection time (capture time for reader items).

    An explicit `since` is used as given. Without one, only items collected within
    DEFAULT_WINDOW are considered, plus reader items sent in within FROM_USER_WINDOW, so the
    old backlog is never judged automatically.
    """
    if since is not None:
        return Item.fetched_at >= _naive_utc(since)
    current = _naive_utc(now) if now is not None else _naive_utc(utcnow())
    return or_(Item.fetched_at >= current - DEFAULT_WINDOW,
               Item.id.in_(_reader_sent_since(current - FROM_USER_WINDOW)))


def _needs_triage():
    """No assessment yet, or a failed triage that has attempts left."""
    retry = and_(Assessment.stage == FAILED_STAGE,
                 Assessment.triage_attempts < MAX_TRIAGE_ATTEMPTS)
    return or_(Assessment.id.is_(None), retry)


def pending_triage_ids(session: Session, *, limit: int, since: datetime | None = None,
                       now: datetime | None = None) -> list[int]:
    """Items in the window to triage, newest first, excluding switched-off feeds.

    That is items with no assessment, plus failed triages that have attempts left.
    """
    stmt = (select(Item.id).outerjoin(Assessment, Assessment.item_id == Item.id)
            .where(_needs_triage(), _keep_condition(), _window(since, now)))
    return list(session.exec(stmt.order_by(_newest_first(), Item.id.desc()).limit(limit)).all())


def skipped_count(session: Session, since: datetime | None = None,
                  now: datetime | None = None) -> int:
    """How many unassessed items in the window are left alone because their feed is off."""
    stmt = (select(func.count(Item.id)).outerjoin(Assessment, Assessment.item_id == Item.id)
            .where(Assessment.id.is_(None), ~_keep_condition(), _window(since, now)))
    return int(session.exec(stmt).one())


def pending_digest_ids(session: Session, *, gate: int, limit: int,
                       since: datetime | None = None, now: datetime | None = None) -> list[int]:
    """Triaged items in the window to digest: over the gate, or sent in by the reader.

    A failed triage is digested only when the reader sent the item (the digest gives its own
    score). Items whose digest reply was unusable MAX_DIGEST_ATTEMPTS times are left alone.
    """
    reader = Item.id.in_(_reader_sent())
    wanted = or_(and_(Assessment.stage == "triage", or_(Assessment.score >= gate, reader)),
                 and_(Assessment.stage == FAILED_STAGE, reader))
    stmt = (select(Item.id).join(Assessment, Assessment.item_id == Item.id)
            .where(wanted, Assessment.digest_attempts < MAX_DIGEST_ATTEMPTS, _keep_condition(),
                   _window(since, now)))
    return list(session.exec(stmt.order_by(_newest_first(), Item.id.desc()).limit(limit)).all())


def _store_triage(engine: Engine, judge: Judge, outcome, users: set[int]) -> dict:
    """Store one triage outcome item by item; returns its counts.

    A malformed reply counts an attempt on the item; an unreachable model stores nothing, so
    the item is simply picked up again by the next run.
    """
    for item_id, result in outcome.results.items():
        store_assessment(engine, item_id, triage_fields(judge, result, None, item_id in users))
    for item_id, error in outcome.errors.items():
        record_triage_failure(engine, item_id, error, model=judge.triage_model,
                              profile_version=judge.version)
    if outcome.unreachable:
        logger.warning("model unreachable for %d items; left for the next run",
                       len(outcome.unreachable))
    return {"triaged": len(outcome.results),
            "failed": len(outcome.errors) + len(outcome.unreachable),
            "unreachable": len(outcome.unreachable)}


def _never() -> bool:
    """Default stop check: never stop."""
    return False


def triage_items(engine: Engine, judge: Judge, item_ids: list[int], *,
                 should_stop: StopFn = _never) -> dict:
    """Triage the given items and store each judgement.

    Batches run a few at a time in parallel and each batch is stored as soon as it returns.
    Items the model could not be reached for get no assessment, so a later run retries them.
    A batch not yet started when `should_stop()` turns true is skipped. Returns
    {"triaged", "failed", "unreachable"}; failed includes the unreachable ones.
    """
    with Session(engine) as session:
        items = session.exec(select(Item).where(Item.id.in_(item_ids))).all()
        rows = [triage_row(i.id, i.title, i.origin, i.source, i.summary) for i in items]
        users = from_user_ids(session, item_ids)
    order = {item_id: n for n, item_id in enumerate(item_ids)}
    rows.sort(key=lambda row: order[row["id"]])
    chunks = [rows[i:i + TRIAGE_BATCH] for i in range(0, len(rows), TRIAGE_BATCH)]
    counts = {"triaged": 0, "failed": 0, "unreachable": 0}

    def work(chunk: list[dict]):
        """One batch, unless a stop was requested before it started."""
        return None if should_stop() else triage_rows(judge, chunk)

    with ThreadPoolExecutor(max_workers=DIGEST_WORKERS) as pool:
        futures = {pool.submit(work, chunk): chunk for chunk in chunks}
        for future in as_completed(futures):
            try:
                outcome = future.result()
                if outcome is None:
                    continue
                part = _store_triage(engine, judge, outcome, users)
            except Exception:  # noqa: BLE001 -- one bad batch must not stop the run
                logger.exception("triage batch failed")
                part = {"triaged": 0, "failed": len(futures[future]), "unreachable": 0}
            counts = {key: counts[key] + part[key] for key in counts}
    return counts


def digest_items(engine: Engine, settings, judge: Judge, item_ids: list[int], *,
                 index=None, fetch: FetchFn | None = None, should_stop: StopFn = _never) -> dict:
    """Digest items in parallel; returns {"digested", "failed", "unreachable"}.

    failed includes the unreachable ones. Items not yet started when `should_stop()` turns
    true are skipped and counted nowhere.
    """
    counts = {"digested": 0, "failed": 0, "unreachable": 0}
    if not item_ids:
        return counts

    def work(item_id: int):
        """One digest, unless a stop was requested before it started."""
        if should_stop():
            return _STOPPED
        return digest_one(engine, settings, judge, item_id, fetch=fetch, index=index)

    with ThreadPoolExecutor(max_workers=DIGEST_WORKERS) as pool:
        futures = {pool.submit(work, item_id): item_id for item_id in item_ids}
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                result = future.result()
                if result is _STOPPED:
                    continue
                ok = result is not None
            except LlmUnavailable as exc:
                logger.warning("digest of item %s deferred: %s", item_id, exc)
                counts["unreachable"] += 1
                ok = False
            except Exception:  # noqa: BLE001 -- one bad item must not stop the run
                logger.exception("digest of item %s failed", item_id)
                ok = False
            counts["digested" if ok else "failed"] += 1
    return counts


def run_pipeline(engine: Engine, settings, index, *, limit: int = DEFAULT_LIMIT,
                 since: datetime | None = None, llm: LlmFn | None = None,
                 fetch: FetchFn | None = None, now: datetime | None = None,
                 should_stop: StopFn | None = None) -> dict:
    """Triage new items and digest the ones worth reading; returns counts.

    limit caps both the items triaged and the items digested in one run. since restricts both
    to items collected at or after that time; without it, only items collected in the last
    DEFAULT_WINDOW (and reader items in the last FROM_USER_WINDOW) are considered, measured
    from `now` (default: the current time). should_stop is checked before each batch and each
    digest, so a service that is shutting down is not kept alive by a long run.

    Returns {"triaged", "digested", "failed", "unreachable", "skipped", "stopped"}: failed
    counts every item that could not be judged this run, unreachable the part of those for
    which the model could not be reached at all (an outage), skipped the unassessed items in
    the window from switched-off feeds, and stopped whether the run ended on a stop request.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stop = should_stop or _never
    convert_legacy_failures(engine)
    judge = make_judge(engine, settings, llm=llm)
    with Session(engine) as session:
        triage_ids = pending_triage_ids(session, limit=limit, since=since, now=now)
        skipped = skipped_count(session, since=since, now=now)
    triaged = {"triaged": 0, "failed": 0, "unreachable": 0}
    if triage_ids and not stop():
        triaged = triage_items(engine, judge, triage_ids, should_stop=stop)
    digested = {"digested": 0, "failed": 0, "unreachable": 0}
    if not stop():
        with Session(engine) as session:
            digest_ids = pending_digest_ids(session, gate=judge.gate, limit=limit, since=since,
                                            now=now)
        digested = digest_items(engine, settings, judge, digest_ids, index=index, fetch=fetch,
                                should_stop=stop)
    counts = {"triaged": triaged["triaged"], "digested": digested["digested"],
              "failed": triaged["failed"] + digested["failed"],
              "unreachable": triaged["unreachable"] + digested["unreachable"],
              "skipped": skipped, "stopped": stop()}
    logger.info("radar pipeline: %s", counts)
    return counts


def _reader_sources(session: Session) -> dict[int, str]:
    """Item id -> how the reader sent it: Raindrop bookmarks and Slack inbox entries."""
    targets = {item_id: "raindrop" for item_id in
               session.exec(select(Item.id).where(Item.source == "raindrop")).all()}
    slack = session.exec(select(Card.item_id).join(InboxEntry, InboxEntry.card_id == Card.id)).all()
    for item_id in slack:
        targets.setdefault(item_id, "slack")
    return targets


def backfill_from_user(engine: Engine) -> int:
    """Mark existing Raindrop bookmarks and Slack inbox items as sent in by the reader.

    Creates `ItemState(from_user=True, captured_via=...)` or flips an existing state; an
    already-assessed item is lifted to the "notable" floor. Idempotent: a second call changes
    nothing and returns 0. Returns the number of items changed.
    """
    with Session(engine) as session:
        targets = _reader_sources(session)
        ids = list(targets)
        states = {s.item_id: s for s in
                  session.exec(select(ItemState).where(ItemState.item_id.in_(ids))).all()}
        assessed = {a.item_id: a for a in
                    session.exec(select(Assessment).where(Assessment.item_id.in_(ids))).all()}
        changed = 0
        for item_id, via in targets.items():
            state = states.get(item_id)
            if state is not None and state.from_user:
                continue
            if state is None:
                session.add(ItemState(item_id=item_id, from_user=True, captured_via=via))
            else:
                state.from_user, state.updated_at = True, utcnow()
                state.captured_via = state.captured_via or via
                session.add(state)
            if item_id in assessed:
                row = assessed[item_id]
                row.tier = tier_for(row.score, from_user=True)
                session.add(row)
            changed += 1
        session.commit()
    return changed
