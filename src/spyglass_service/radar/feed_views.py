"""Saved views of the Feed: "Missed" (`missed=true`) and one Watch group (`watch_group=<name>`).

Both are extra filters on GET /feed. They live here so the route stays small:

- **Missed** is what the reader would want to catch up on after days away: items of the last 7
  days (by the date the Feed is ordered on) judged top or notable that the reader has never
  opened, saved, filed, queued for filing, voted away or dismissed, and did not send in
  themselves. It is ordered by score, then newest first, and is returned as one page of up to
  `limit` items (the Feed asks for the most the route allows) with no `next_before`, because a
  date cursor cannot page a list ordered by score.
- **Watch group** is the items linked to any followed name of the group that were fetched in the
  last 7 days and are not judged "out". It reuses the register's own week query, so the number on
  the Watch page heading and the number of rows here are the same by construction. An unknown
  group is simply empty.

A view carries its own quality rules (the Feed's default hiding of old unjudged items does not
apply), so the route skips those rules when a view is active.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Engine, false, func
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.filed import filed_condition
from spyglass_service.radar.filing_queue import waiting_condition
from spyglass_service.radar.models import Assessment, ItemState, Signal, WatchEntity
from spyglass_service.radar.watch import registry

# How far back "Missed" looks.
MISSED_WINDOW = timedelta(days=7)
# Tiers worth catching up on; skim items are not "missed".
MISSED_TIERS = ("top", "notable")
# Reader actions that mean an item was seen or dealt with. `unsave` is not listed: saving it once
# already counts, whether or not the save was taken back.
_SEEN_SIGNALS = ("open", "save", "vault")


@dataclass(frozen=True)
class FeedView:
    """What a saved view adds to a feed request.

    `conditions` are extra WHERE terms; `order` is the ordering; `single_page` means the view is
    ordered by something a date cursor cannot page, so `before` is ignored and there is no next page.
    """

    conditions: tuple[ColumnElement, ...] = ()
    order: tuple[ColumnElement, ...] = ()
    single_page: bool = False


def _naive_utc_now() -> datetime:
    """The current time as the naive UTC the database stores."""
    return datetime.now(UTC).replace(tzinfo=None)


def recent_condition(sort_key: ColumnElement, now: datetime | None = None) -> ColumnElement:
    """True for an item whose feed date is within the Missed window (the edge itself is inside)."""
    return sort_key >= (now or _naive_utc_now()) - MISSED_WINDOW


def missed_conditions(sort_key: ColumnElement, now: datetime | None = None) -> tuple[ColumnElement, ...]:
    """The WHERE terms of the Missed view; needs Assessment and ItemState outer-joined to Item."""
    seen = select(Signal.item_id).where(Signal.kind.in_(_SEEN_SIGNALS), Signal.item_id.is_not(None))
    return (
        Assessment.tier.in_(MISSED_TIERS),
        recent_condition(sort_key, now),
        ItemState.opened_at.is_(None),
        ItemState.saved_at.is_(None),
        # A missing state row (outer join) reads as NULL, which means "nothing done".
        func.coalesce(ItemState.hidden, false()).is_(False),
        func.coalesce(ItemState.from_user, false()).is_(False),
        Item.id.not_in(seen),
        ~filed_condition(),
        ~waiting_condition(),
    )


def watch_group_item_ids(session: Session, group: str, now: datetime | None = None) -> set[int]:
    """Ids of the items the Watch page counts for `group` this week; empty for an unknown group.

    A group is the entities' category (those without one are in "Other"); suggested names are not
    followed, so they are not in it. The week query is the register's own.
    """
    entities = session.exec(select(WatchEntity).where(WatchEntity.status != "suggested")).all()
    wanted = [e.id for e in entities if e.id is not None and (e.category or registry.OTHER) == group]
    # The register's own query: one definition of "this week" for the heading and for these rows.
    found = registry._week_item_ids(session, wanted, now)  # noqa: SLF001
    return set().union(*found.values()) if found else set()


def feed_view(engine: Engine, *, missed: bool | None, watch_group: str | None, sort_key: ColumnElement,
              now: datetime | None = None) -> FeedView:
    """The saved view a feed request asks for (`missed`, `watch_group`, both, or neither)."""
    conditions: list[ColumnElement] = []
    if missed:
        conditions.extend(missed_conditions(sort_key, now))
    if watch_group is not None:
        with Session(engine) as session:
            conditions.append(Item.id.in_(sorted(watch_group_item_ids(session, watch_group, now))))
    if not conditions:
        return FeedView(order=(sort_key.desc(), Item.id.desc()))
    if missed:
        return FeedView(tuple(conditions), (Assessment.score.desc(), sort_key.desc(), Item.id.desc()), single_page=True)
    return FeedView(tuple(conditions), (sort_key.desc(), Item.id.desc()))
