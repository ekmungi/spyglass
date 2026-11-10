# src/spyglass_service/brief_time.py
"""Windowing time primitives shared by brief.py and brief_narrative.py.

Kept in its own module (rather than inside brief_narrative.py) so both brief.py and
brief_narrative.py can import it without creating a cycle: brief.py already imports
brief_narrative, so a helper living in brief_narrative would still be reachable, but a
neutral module keeps the dependency direction obvious.

The window-free eligibility query (`eligible_pairs`) and the publish-day bucketing pure
functions (`briefed_days`, `days_to_compose`) drive `compose_due_briefs` in brief.py, which
composes one brief per un-briefed local day instead of a single covers_from/until window.
The featured/listed relevance split lives here as
`_split_by_relevance` (used by `eligible_pairs`); the base eligibility filters live here
as `_base_eligibility_query`. The dependency stays one-directional (brief.py imports
brief_time; brief_time.py never imports brief.py), so no cycle.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Engine, or_
from sqlmodel import Session, select

from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, CardState, Feed, Item
from spyglass_service.relevance_serve import effective_relevance_map


def local_day(card: Card, item: Item, *, tz: timezone | None = None, today: date | None = None) -> date:
    """Return the local calendar day a card belongs to, for publish-day windowing.

    Prefers the item's publish time; falls back to the card's fetch time when the
    source did not supply one (e.g. some non-RSS collectors). Both timestamps are
    stored naive-UTC (DEC pattern across the schema), so they are first tagged UTC,
    then converted to the target timezone (machine-local when tz is None) before
    taking the date -- this is what lets a late-UTC-evening story land on the
    correct NEXT local day (or a small-hours UTC story land on the PREVIOUS local
    day) instead of always keying off the UTC calendar date.

    Args:
        card: The Card row (used for its created_at fallback).
        item: The Item row (used for its published_at, when present).
        tz: Target timezone for the local-day conversion. None means the machine's
            local timezone (production default). Tests pass an explicit tz so
            results don't depend on the machine running them.
        today: The "today" cap for clamping a future local day. None means the
            real current date in `tz` (production default). Tests pass an
            explicit today for determinism.

    Returns:
        The local calendar date, clamped to `today` so a future-dated or
        clock-skewed publish time never produces a day after today.
    """
    # (item.published_at or card.created_at) is naive UTC (see models.py); attach the
    # UTC tzinfo explicitly before converting, since naive datetimes can't be
    # astimezone()'d correctly otherwise.
    base = item.published_at if item.published_at is not None else card.created_at
    day = base.replace(tzinfo=timezone.utc).astimezone(tz).date()
    cap = today if today is not None else datetime.now(tz).date()
    # Clamp rather than reject: a future-dated feed entry or minor clock skew should
    # not push a card's brief-window day beyond today.
    return min(day, cap)


def local_day_of(dt: datetime, tz: timezone | None, today: date | None) -> date:
    """Return the local calendar day for a raw (naive-UTC) datetime.

    Same conversion rule as `local_day`'s core (tag UTC, convert to tz, clamp to
    today), but for callers that only have a bare datetime -- e.g. a Brief's
    covers_from/covers_until -- rather than a (Card, Item) pair.

    Args:
        dt: A naive-UTC datetime (the schema's storage convention).
        tz: Target timezone; None means the machine's local timezone.
        today: The "today" cap; None means the real current date in `tz`.

    Returns:
        The local calendar date, clamped to `today`.
    """
    day = dt.replace(tzinfo=timezone.utc).astimezone(tz).date()
    cap = today if today is not None else datetime.now(tz).date()
    return min(day, cap)


def _split_by_relevance(
    rows: list[tuple[Card, Item]], effective: dict[int, str | None]
) -> tuple[list[tuple[Card, Item]], list[tuple[Card, Item]]]:
    """Bucket (Card, Item) rows into featured (medium/high) vs listed (low).

    Cards whose effective relevance is out or unjudged (None) are excluded from
    both buckets entirely. Used by `eligible_pairs` (below) after it queries the
    un-briefed rows and computes their effective relevance.

    Args:
        rows: (Card, Item) tuples in the caller's desired order (order is
            preserved in the output lists).
        effective: card.id -> effective relevance level, as returned by
            `effective_relevance_map`.

    Returns:
        (featured, listed) -- new lists, `rows` is never mutated.
    """
    featured = [(card, item) for card, item in rows if effective[card.id] in ("medium", "high")]
    listed = [(card, item) for card, item in rows if effective[card.id] == "low"]
    return featured, listed


def _base_eligibility_query():
    """The eligibility filters shared by every brief-eligibility query, minus any
    created_at window bound: enabled (or feedless) source, not dismissed, not yet
    stamped by a brief. Callers add their own window predicate (or none) and order.

    Returns:
        A partially-built select(Card, Item) statement (no order_by yet). Statement
        construction needs no session -- SQLAlchemy select() objects are built
        independently of any session and only executed against one later.
    """
    return (
        select(Card, Item)
        .join(Item, Card.item_id == Item.id)
        .outerjoin(Feed, Item.feed_url == Feed.feed_url)
        .where(or_(Feed.enabled == True, Feed.id == None))  # noqa: E711, E712
        .where(Card.state != CardState.DISMISSED)
        .where(Card.brief_id == None)  # noqa: E711 -- not yet covered by any brief
    )


def eligible_pairs(
    engine: Engine, index: EmbeddingIndex
) -> tuple[list[tuple[Card, Item]], list[tuple[Card, Item]]]:
    """Select ALL un-briefed cards (no date window) and split them by effective relevance.

    The eligibility source for publish-day windowing: the shared feed/state/brief_id
    filters (`_base_eligibility_query`) and the featured/listed relevance split
    (`_split_by_relevance`), with no created_at bound at all -- a card is eligible the
    moment it exists and is un-briefed, however old. This is what lets
    `compose_due_briefs` brief an old un-briefed day without an artificial 72h cutoff.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (for the k-NN relevance blend).

    Returns:
        (featured, listed) lists of (Card, Item) tuples, newest first.
    """
    with Session(engine) as session:
        statement = _base_eligibility_query().order_by(Card.created_at.desc())  # type: ignore[attr-defined]
        rows = list(session.exec(statement).all())
        effective = effective_relevance_map(engine, index, rows)
    return _split_by_relevance(rows, effective)


def briefed_days(
    engine: Engine, *, tz: timezone | None = None, today: date | None = None
) -> set[date]:
    """Return the set of local days already claimed by ANY existing brief.

    Union, over every Brief row, of: (a) the local_day of each card currently
    stamped with that brief's id, and (b) the FULL inclusive local-day range
    covers_from..covers_until. Part (b) matters for a multi-day digest brief: its
    span claims every day it covers, even a day inside the span with zero stamped
    cards (e.g. a genuinely quiet day) -- otherwise a late-arriving item for that
    gap day would look "unbriefed" and spin off a stray single-day brief inside a
    span that was already digested.

    Args:
        engine: SQLAlchemy engine.
        tz: Target timezone for the local-day conversion; None means machine-local.
        today: The "today" cap for clamping; None means the real current date.

    Returns:
        Set of local calendar days already claimed by some brief.
    """
    claimed: set[date] = set()
    with Session(engine) as session:
        briefs = list(session.exec(select(Brief)).all())
        for brief in briefs:
            # (a) days of cards this brief actually stamped.
            stamped = session.exec(
                select(Card, Item).join(Item, Card.item_id == Item.id).where(Card.brief_id == brief.id)
            ).all()
            for card, item in stamped:
                claimed.add(local_day(card, item, tz=tz, today=today))
            # (b) the brief's whole covered span, day by day inclusive -- claims gap
            # days even when no card landed on them.
            start = local_day_of(brief.covers_from, tz, today)
            end = local_day_of(brief.covers_until, tz, today)
            day = start
            while day <= end:
                claimed.add(day)
                day += timedelta(days=1)
    return claimed


def days_to_compose(
    engine: Engine,
    index: EmbeddingIndex,
    *,
    tz: timezone | None = None,
    today: date | None = None,
    horizon_days: int | None = None,
) -> list[date]:
    """Return the distinct local days with eligible cards that no brief has claimed yet.

    Union of every eligible card's local_day (featured OR listed, from
    `eligible_pairs`), minus `briefed_days`, minus anything outside the recency
    horizon (when set), sorted newest-first -- the compose loop works
    through this list to decide what to brief next.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (for the k-NN relevance blend).
        tz: Target timezone for the local-day conversion; None means machine-local.
        today: The "today" cap for clamping; None means the real current date.
        horizon_days: Recency horizon in days. When
            set and > 0, only local days >= (today - horizon_days) are kept -- this is
            applied on local_day (not created_at), so it is robust to coarse/wrong
            published_at and directly bounds the digest span rather than the DB-row
            age. None or <= 0 means no horizon (unbounded):
            the whole never-briefed backlog stays eligible, however old. Older
            never-briefed cards outside the horizon simply stay unbriefed -- they are
            never dropped, only deferred until they fall inside a future horizon
            (impossible as time moves forward) or the horizon is widened.

    Returns:
        Local calendar days to compose, sorted descending (newest first).
    """
    featured, listed = eligible_pairs(engine, index)
    eligible_days = {local_day(card, item, tz=tz, today=today) for card, item in featured + listed}
    remaining = eligible_days - briefed_days(engine, tz=tz, today=today)
    if horizon_days is not None and horizon_days > 0:
        # cap is the same today/tz seam local_day clamps against, so "recent" always
        # means "recent relative to the caller's notion of today", not the wall clock.
        cap = today if today is not None else datetime.now(tz).date()
        cutoff = cap - timedelta(days=horizon_days)
        remaining = {d for d in remaining if d >= cutoff}
    return sorted(remaining, reverse=True)
