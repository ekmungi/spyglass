"""The daily watch sweep: search news for each watched entity and link items to entities.

Four steps, each independent: `watch_collect` fetches news per entity; the caller stores the
items with `ingest.store_items`; `link_watch_items` ties stored items to the entity whose
search found them; `link_mentions` also ties assessed items that merely name an entity; and
`suggest_from_mentions` proposes organisations that keep appearing but are not registered.
"""

import dataclasses
import logging
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, ItemEntity, WatchEntity, loads, utcnow
from spyglass_service.radar.watch._news_fallback import SearchFn, default_search
from spyglass_service.radar.watch.registry import create_entity, entity_names, known_names, norm_name

logger = logging.getLogger(__name__)

# Seconds between two news searches, so a sweep over many entities stays polite.
SEARCH_PAUSE = 1.0
# A daily sweep only needs the last few days of news.
SWEEP_DAYS = 3
TAG_PREFIX = "watch:"
# Mentions older than this do not count towards suggesting a new entity.
SUGGEST_WINDOW = timedelta(days=30)
# At most this many new suggestions per run, most-mentioned first.
SUGGEST_MAX_NEW = 10


def _entity_ids(tags: str | None) -> list[int]:
    """Entity ids named by `watch:<id>` tags in a comma-joined tag string."""
    ids = []
    for tag in (tags or "").split(","):
        tag = tag.strip()
        if tag.startswith(TAG_PREFIX) and tag[len(TAG_PREFIX):].isdigit():
            ids.append(int(tag[len(TAG_PREFIX):]))
    return ids


def _add_links(session: Session, pairs: set[tuple[int, int]], via: str) -> list[int]:
    """Insert missing (item_id, entity_id) links; returns the entity ids that gained a link."""
    if not pairs:
        return []
    existing = set(session.exec(select(ItemEntity.item_id, ItemEntity.entity_id)).all())
    gained = []
    for item_id, entity_id in sorted(pairs - existing):
        session.add(ItemEntity(item_id=item_id, entity_id=entity_id, via=via))
        gained.append(entity_id)
    return gained


def _bump(session: Session, entity_ids: list[int]) -> None:
    """Set last_hit_at to now on the given entities."""
    now = utcnow()
    for entity_id in set(entity_ids):
        entity = session.get(WatchEntity, entity_id)
        if entity is not None:
            entity.last_hit_at = now
            session.add(entity)


def watch_collect(
    engine: Engine,
    settings,
    *,
    search: SearchFn | None = None,
    pause: float = SEARCH_PAUSE,
    sleep: Callable[[float], None] = time.sleep,
) -> list[CollectedItem]:
    """Search news for every active entity; items are tagged `watch:<entity id>`.

    One failed search is logged and skipped. An item found by several entities comes back once
    with all their tags. Items already stored are linked straight away, because the ingest step
    never touches existing rows and would otherwise lose the new link.
    """
    search = search or default_search()
    with Session(engine) as session:
        entities = session.exec(select(WatchEntity).where(WatchEntity.status == "active")).all()
        targets = [(e.id, e.query or f'"{e.name}"') for e in entities]
    merged: dict[str, CollectedItem] = {}
    for n, (entity_id, query) in enumerate(targets):
        if n:
            sleep(pause)
        try:
            found = search(query, days=SWEEP_DAYS)
        except Exception:
            logger.exception("Watch search failed for entity %s", entity_id)
            continue
        for item in found:
            tag = f"{TAG_PREFIX}{entity_id}"
            previous = merged.get(item.external_id)
            tags = [*previous.source_tags, tag] if previous else [tag]
            merged[item.external_id] = dataclasses.replace(
                previous or item, source="watch", source_tags=list(dict.fromkeys(tags))
            )
    items = list(merged.values())
    _link_already_stored(engine, items)
    return items


def _link_already_stored(engine: Engine, items: list[CollectedItem]) -> None:
    """Link items that are already in the database to the entities that found them again."""
    if not items:
        return
    with Session(engine) as session:
        stored = dict(
            session.exec(select(Item.external_id, Item.id).where(Item.source == "watch")).all()
        )
        pairs = {
            (stored[i.external_id], eid)
            for i in items if i.external_id in stored
            for eid in _entity_ids(",".join(i.source_tags))
        }
        _bump(session, _add_links(session, pairs, "query"))
        session.commit()


def link_watch_items(engine: Engine) -> int:
    """Link stored watch items to the entities in their tags; returns how many links were new."""
    with Session(engine) as session:
        valid = set(session.exec(select(WatchEntity.id)).all())
        rows = session.exec(select(Item.id, Item.source_tags).where(Item.source_tags.contains(TAG_PREFIX))).all()
        pairs = {(item_id, eid) for item_id, tags in rows for eid in _entity_ids(tags) if eid in valid}
        gained = _add_links(session, pairs, "query")
        _bump(session, gained)
        session.commit()
    return len(gained)


def link_mentions(engine: Engine) -> int:
    """Link assessed items whose named organisations match an active entity's name or alias.

    Matching is on the whole name, ignoring case and punctuation, so "Intuitive" does not match
    "Intuitive Surgical". Returns how many links were new.
    """
    with Session(engine) as session:
        lookup: dict[str, int] = {}
        for e in session.exec(select(WatchEntity).where(WatchEntity.status == "active")).all():
            for name in entity_names(e):
                lookup.setdefault(norm_name(name), e.id)
        if not lookup:
            return 0
        pairs: set[tuple[int, int]] = set()
        for item_id, raw in session.exec(
            select(Assessment.item_id, Assessment.entities).where(Assessment.entities.is_not(None))
        ).all():
            for name in loads(raw, []) or []:
                eid = lookup.get(norm_name(str(name)))
                if eid is not None:
                    pairs.add((item_id, eid))
        gained = _add_links(session, pairs, "mention")
        session.commit()
    return len(gained)


def unknown_mentions(
    session: Session, min_count: int = 3, max_new: int = SUGGEST_MAX_NEW, *, now: datetime | None = None
) -> list[tuple[str, int]]:
    """Organisations named in at least `min_count` relevant recent items and not in the register.

    Counts distinct non-"out" items from the last 30 days (`SUGGEST_WINDOW`), whatever the
    register's status for a name, so a suggestion or a muted entry is never named again. Returns
    `(name as most often written, item count)`, most-mentioned first, at most `max_new`.
    `now` (naive UTC) is only for tests.
    """
    cutoff = (now or utcnow().replace(tzinfo=None)) - SUGGEST_WINDOW
    rows = session.exec(
        select(Assessment.item_id, Assessment.entities, Item.published_at, Item.fetched_at)
        .join(Item, Item.id == Assessment.item_id)
        .where(Assessment.entities.is_not(None), Assessment.tier != "out")
    ).all()
    items_by_name: dict[str, set[int]] = {}
    forms: dict[str, Counter] = {}
    for item_id, raw, published, fetched in rows:
        if (published or fetched) < cutoff:
            continue
        for name in loads(raw, []) or []:
            key = norm_name(str(name))
            if len(key) < 3:
                continue
            items_by_name.setdefault(key, set()).add(item_id)
            forms.setdefault(key, Counter())[str(name).strip()] += 1
    taken = known_names(session)
    ranked = sorted(
        ((len(ids), key) for key, ids in items_by_name.items() if len(ids) >= min_count and key not in taken),
        reverse=True,
    )[:max_new]
    return [(forms[key].most_common(1)[0][0], count) for count, key in ranked]


def suggest_from_mentions(
    engine: Engine, min_count: int = 3, max_new: int = SUGGEST_MAX_NEW, *, now: datetime | None = None
) -> int:
    """Propose unregistered organisations named in at least `min_count` relevant recent items.

    New entries get status "suggested" for the reader to accept (see `unknown_mentions` for how
    names are counted). `now` (naive UTC) is only for tests. Returns how many were added.
    """
    with Session(engine) as session:
        found = unknown_mentions(session, min_count, max_new, now=now)
        for name, count in found:
            create_entity(
                session, name, category="Discovered", status="suggested",
                added_via="discovered", why=f"named in {count} relevant items",
            )
    return len(found)
