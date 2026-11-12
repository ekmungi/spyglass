"""The compact picture of the watch register that the review reads.

One row per followed name: how much it brought into the Feed, how long it has been quiet and
how much of it the reader engaged with. Alongside it go the reader's sections and topics and the
organisations that keep appearing in relevant items without being on the list.
"""

from datetime import datetime, timedelta

from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, ItemEntity, ItemState, WatchEntity, utcnow
from spyglass_service.radar.profile_defaults import load_profile
from spyglass_service.radar.watch.registry import OTHER, WEEK
from spyglass_service.radar.watch.sweep import unknown_mentions

# The look-back of the per-name "items this month" count.
MONTH = timedelta(days=30)
# Biggest register the review sends to the model; a longer one is cut after this many names.
MAX_ENTRIES = 200
# Most unregistered names shown to the model or offered by the basic review.
MAX_UNREGISTERED = 15
# An unregistered name needs this many relevant items to be mentioned to the model at all.
UNREGISTERED_MIN_ITEMS = 2


def _engagement(session: Session, entity_ids: list[int], now: datetime) -> dict[int, dict[str, int]]:
    """Per entity: items this week and month (not judged out) and items the reader opened or saved.

    One query over every link. A link to an item judged "out" counts for nothing; an item the
    reader opened or saved counts as engaged however old it is.
    """
    rows = session.exec(
        select(ItemEntity.entity_id, Item.id, Item.fetched_at, ItemState.opened_at, ItemState.saved_at)
        .join(Item, Item.id == ItemEntity.item_id)
        .outerjoin(Assessment, Assessment.item_id == Item.id)
        .outerjoin(ItemState, ItemState.item_id == Item.id)
        .where(ItemEntity.entity_id.in_(entity_ids))
        .where((Assessment.id.is_(None)) | (Assessment.tier != "out"))
    ).all() if entity_ids else []
    stats = {eid: {"week": 0, "month": 0, "engaged": 0} for eid in entity_ids}
    for entity_id, _item_id, fetched, opened, saved in rows:
        row = stats[entity_id]
        if fetched >= now - WEEK:
            row["week"] += 1
        if fetched >= now - MONTH:
            row["month"] += 1
        if opened is not None or saved is not None:
            row["engaged"] += 1
    return stats


def _days(then: datetime, now: datetime) -> int:
    """Whole days from `then` to `now`, never negative."""
    return max(0, (now - then).days)


def build_picture(session: Session, *, now: datetime | None = None) -> dict:
    """The review's input: `register`, `profile` and `unregistered`.

    register: followed names (active or muted; suggestions are not reviewed) with id, name,
    category, kind, status, idle_days (since the last hit, or since it was added when it never
    had one), ever_hit, added_days_ago, week_count, month_count and engaged. `now` is naive UTC
    and only for tests.
    """
    now = now or utcnow().replace(tzinfo=None)
    entities = [e for e in session.exec(select(WatchEntity)).all() if e.status != "suggested"]
    entities.sort(key=lambda e: e.name.lower())
    entities = entities[:MAX_ENTRIES]
    stats = _engagement(session, [e.id for e in entities], now)
    register = [
        {
            "id": e.id, "name": e.name, "category": e.category or OTHER, "kind": e.kind, "status": e.status,
            "idle_days": _days(e.last_hit_at or e.created_at, now), "ever_hit": e.last_hit_at is not None,
            "added_days_ago": _days(e.created_at, now),
            "week_count": stats[e.id]["week"], "month_count": stats[e.id]["month"], "engaged": stats[e.id]["engaged"],
        }
        for e in entities
    ]
    profile = load_profile(session)
    unknown = unknown_mentions(session, UNREGISTERED_MIN_ITEMS, MAX_UNREGISTERED, now=now)
    return {
        "register": register,
        "profile": {
            "sections": [str(s.get("label") or s.get("key")) for s in profile.get("sections", [])],
            "topics": [str(t.get("name")) for t in profile.get("topics", []) if t.get("name")],
        },
        "unregistered": [{"name": name, "items": count} for name, count in unknown],
    }
