# src/spyglass_service/brief.py
"""Daily Brief composition: publish-day windowing, eligibility, compose + recompose.

Each un-briefed local publish-day gets its OWN brief (newest first), with no cap on the number
of days and no folded "earlier" digest, so a long gap yields one brief per in-horizon day
(days_to_compose already bounds the list by the recency horizon). Featured items (effective
relevance medium/high) get an LLM narrative; low items are listed; the compose job stamps every
covered card with the brief id so it is never covered twice. The narrative call + markdown
assembly live in brief_narrative (shared with recompose).
"""

import logging
from datetime import UTC, date, datetime, timezone

from sqlalchemy import Engine
from sqlmodel import Session, select

# Re-exported so existing callers keep importing these from spyglass_service.brief.
from spyglass_service.brief_narrative import BriefComposeError as BriefComposeError
from spyglass_service.brief_narrative import LlmFn, narrative_and_markdown
from spyglass_service.brief_time import (
    days_to_compose,
    eligible_pairs,
    local_day,
)
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, Item
from spyglass_service.relevance_serve import effective_relevance_map

logger = logging.getLogger(__name__)

# Max featured items given a full narrative write-up; overflow spills to "listed" so a
# large day stays readable and the narrative prompt stays bounded (tune against a real day).
FEATURED_CAP = 30


def _cap_featured(
    featured: list[tuple[Card, Item]],
    listed: list[tuple[Card, Item]],
    effective: dict[int, str | None],
) -> tuple[list[tuple[Card, Item]], list[tuple[Card, Item]]]:
    """Keep at most FEATURED_CAP featured items (high before medium, recency tiebreak);
    the rest spill into the listed tail so no eligible item is silently dropped.

    Args:
        featured: Featured (Card, Item) rows, newest first.
        listed: Listed (Card, Item) rows, newest first.
        effective: card.id -> effective relevance level, used to rank high before medium.

    Returns:
        (featured, listed) unchanged when featured is already within the cap, otherwise
        (kept, overflow + listed) -- new lists, inputs are never mutated.
    """
    if len(featured) <= FEATURED_CAP:
        return featured, listed
    # stable sort: high before medium; within a level the incoming recency order (newest-first) holds
    ranked = sorted(featured, key=lambda ci: 0 if effective[ci[0].id] == "high" else 1)
    kept = ranked[:FEATURED_CAP]
    overflow = ranked[FEATURED_CAP:]
    return kept, overflow + listed  # overflow (higher relevance) ahead of the low items


def _publish_ts(card: Card, item: Item) -> datetime:
    """The naive-UTC publish timestamp used for a card's brief-span bounds.

    Prefers the item's published_at; falls back to the card's created_at when the
    source supplied no publish time -- the same precedence local_day uses, so a
    card's span contribution and its bucket day are always derived consistently.

    Args:
        card: The Card row (created_at fallback).
        item: The Item row (published_at when present).

    Returns:
        The naive-UTC datetime to fold into covers_from/covers_until.
    """
    return item.published_at if item.published_at is not None else card.created_at


def _compose_bucket(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    featured: list[tuple[Card, Item]],
    listed: list[tuple[Card, Item]],
    publish_day: date,
    effective: dict[int, str | None],
    *,
    llm: LlmFn | None,
) -> Brief | None:
    """Compose ONE publish-day bucket in its own transaction.

    Applies the FEATURED_CAP cap, writes the narrative, then persists the Brief and
    stamps every member card atomically. covers_from/covers_until span the members'
    publish timestamps; publish_day is the bucket's key day (ISO). A bucket with no
    members is skipped (returns None) -- never an empty brief.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (relevance blend + related links).
        settings: App settings (model, API key, interest note path).
        featured: This bucket's featured (Card, Item) rows, newest first.
        listed: This bucket's listed (Card, Item) rows, newest first.
        publish_day: The bucket's key local day (newest day of the bucket).
        effective: card.id -> effective relevance level for the whole run's eligible
            cards, used to rank high before medium inside the cap (computed once by the
            caller so every bucket sees the same levels the featured/listed split used).
        llm: Injectable LLM callable (tests); None means the real OpenRouter call.

    Returns:
        The persisted Brief, or None when the bucket had no members.

    Raises:
        BriefComposeError: The LLM call failed or returned a malformed payload;
            nothing was written for this bucket (caller pauses only this bucket).
    """
    if not featured and not listed:
        return None  # guard: eligible days shouldn't be empty, but never write an empty brief
    # Cap featured per bucket so a heavy day stays readable (same rule the old window used).
    featured, listed = _cap_featured(featured, listed, effective)

    markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)

    # Span the members' publish timestamps (naive UTC, matching the schema convention).
    stamps = [_publish_ts(card, item) for card, item in featured + listed]
    covers_from, covers_until = min(stamps), max(stamps)

    # Single transaction per bucket: the Brief row and every member's stamp land together,
    # so a crash (or a later bucket's failure) can never leave cards claimed by a brief
    # that does not exist. Other buckets have already committed in their own transactions.
    with Session(engine) as session:
        brief = Brief(
            covers_from=covers_from, covers_until=covers_until,
            markdown=markdown, item_count=len(featured), low_count=len(listed),
            publish_day=publish_day.isoformat(),
        )
        session.add(brief)
        session.flush()  # assigns brief.id for the stamps below
        for card, _item in featured + listed:
            covered = session.get(Card, card.id)
            if covered is None:
                continue  # deleted mid-compose; skipping beats crashing the whole bucket txn
            covered.brief_id = brief.id
            covered.updated_at = datetime.now(UTC)
            session.add(covered)
        session.commit()
        session.refresh(brief)
    return brief


def compose_due_briefs(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    *,
    now: datetime | None = None,
    tz: timezone | None = None,
    today: date | None = None,
    llm: LlmFn | None = None,
) -> list[Brief]:
    """Compose every due Daily Brief -- one per un-briefed publish-day, newest first.

    Replaces the single-window compose_brief. Steps: find the un-briefed local days
    (days_to_compose, already bounded by the recency horizon), then compose ONE single-day
    brief per day in its own transaction (no day cap and no folded
    "earlier" digest). Cards come from ONE eligible_pairs query, filtered per day by
    local_day -- eligibility is never re-queried per day.

    Self-limiting: it only ever composes days no brief has claimed, so a repeated
    call (e.g. every startup pass) is a no-op once the backlog is drained -- no guard
    needed. Per-bucket pause: if a bucket's narrative raises, that bucket is
    logged and skipped (its cards stay eligible for a retry) while the buckets that
    already committed survive.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (relevance blend + related links).
        settings: App settings (model, API key, interest note path).
        now: Compose-time override; None means the real current time. Supplies `today`
            when `today` is not given, so a caller can compose "as of" a moment without
            also restating the date. `today` wins when both are passed.
        tz: Target timezone for local-day conversion; None means machine-local.
        today: The "today" cap for clamping a future local day; None means the real
            current date in tz -- or the local date of `now`, when that was supplied.
        llm: Injectable LLM callable (tests); defaults to the real OpenRouter call.

    Returns:
        The list of persisted Briefs, newest first (possibly empty). A bucket that
        paused (LLM failure) is absent from the list; its cards remain eligible.
    """
    # If `now` were ignored, a caller passing it would
    # silently get a window derived from the real clock. That is a trap -- a test written
    # against `now` passes today and expires the moment the seeded day drifts outside
    # `brief_horizon_days`.
    # Resolving it into `today` makes the parameter mean what every caller assumes.
    # `today` stays the authority when both are given.
    if today is None and now is not None:
        # Same conversion the rest of the brief path uses for a "current date in tz"
        # (cf. brief_time.local_day's `datetime.now(tz).date()`): an aware `now` converts
        # exactly; a naive one is read as machine-local, matching astimezone's contract.
        today = now.astimezone(tz).date()
    # Bound eligibility to the configured recency
    # horizon so a long-idle never-briefed backlog can't flood the run with one brief per
    # ancient day -- see days_to_compose's horizon_days docstring for the predicate.
    days = days_to_compose(engine, index, tz=tz, today=today, horizon_days=settings.brief_horizon_days)
    if not days:
        return []

    # One eligibility query for the whole run; each bucket filters this by local_day so we
    # never re-hit the DB per day. featured/listed stay split as eligible_pairs returned them.
    featured, listed = eligible_pairs(engine, index)
    # One effective-relevance map over the whole eligible set, shared by every bucket's cap
    # ranking -- so a per-bucket subset never recomputes (and possibly disagrees with) the
    # levels the featured/listed split was made on.
    effective = effective_relevance_map(engine, index, featured + listed)

    def _members(
        pairs: list[tuple[Card, Item]], wanted: set[date]
    ) -> list[tuple[Card, Item]]:
        """Rows whose local_day is in `wanted`, preserving the input (newest-first) order."""
        return [
            (card, item)
            for card, item in pairs
            if local_day(card, item, tz=tz, today=today) in wanted
        ]

    # One single-day brief per un-briefed publish-day, newest first -- no folded
    # "earlier" digest. days_to_compose is descending and already horizon-bounded, so this is
    # at most one brief per in-horizon day (never a lump, never an unbounded flood).
    plan: list[tuple[date, set[date]]] = [(d, {d}) for d in days]

    composed: list[Brief] = []
    for key_day, wanted in plan:
        featured_b = _members(featured, wanted)
        listed_b = _members(listed, wanted)
        try:
            brief = _compose_bucket(
                engine, index, settings, featured_b, listed_b, key_day, effective, llm=llm
            )
        except BriefComposeError:
            # Per-bucket pause: log, write nothing for this bucket, continue to the next.
            # Already-committed buckets stay; this bucket's cards remain eligible for retry.
            logger.exception("daily brief bucket %s paused (LLM unavailable)", key_day.isoformat())
            continue
        if brief is not None:
            composed.append(brief)
    return composed


def recompose_brief(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    brief_id: int,
    *,
    llm: LlmFn | None = None,
) -> Brief | None:
    """Re-run the narrative + assembly over a brief's already-stamped cards, in place.

    Membership is already decided (Card.brief_id == brief_id), so neither the window
    nor the feed-disabled filter applies here -- only featured/listed are recomputed
    from the CURRENT effective relevance (thumbs given since compose move items between
    the narrative and the tail). covers_* and the stamped membership never change;
    markdown/item_count/low_count are overwritten on the same row.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (relevance blend + related links).
        settings: App settings (model, API key, interest note path).
        brief_id: The brief to rebuild.
        llm: Injectable LLM callable (tests); defaults to the real OpenRouter call.

    Returns:
        The updated Brief, or None for an unknown id.

    Raises:
        BriefComposeError: The LLM call failed or returned a malformed payload; the
            stored brief is untouched (nothing is written before the narrative lands).
    """
    with Session(engine) as session:
        brief = session.get(Brief, brief_id)
        if brief is None:
            return None
        rows = list(session.exec(
            select(Card, Item)
            .join(Item, Card.item_id == Item.id)
            .where(Card.brief_id == brief_id)
            .order_by(Card.created_at.desc())  # type: ignore[attr-defined]
        ).all())
    effective = effective_relevance_map(engine, index, rows)
    featured = [(card, item) for card, item in rows if effective[card.id] in ("medium", "high")]
    # Everything below the featured bar stays listed -- membership is fixed, so even a
    # card thumbed down to 'out' since compose remains visible in the tail rather than
    # silently vanishing from a brief that already covered it.
    listed = [(card, item) for card, item in rows if effective[card.id] not in ("medium", "high")]
    # Same cap as compose: without this, a recompose would re-bucket the compose-time
    # overflow by relevance and let it climb back into featured, silently un-capping
    # a large brief.
    featured, listed = _cap_featured(featured, listed, effective)

    markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)

    # Overwrite in place only after the narrative succeeded (pause leaves it untouched).
    with Session(engine) as session:
        stored = session.get(Brief, brief_id)
        if stored is None:
            return None  # deleted mid-recompose; nothing to overwrite
        stored.markdown = markdown
        stored.item_count = len(featured)
        stored.low_count = len(listed)
        session.add(stored)
        session.commit()
        session.refresh(stored)
    return stored
