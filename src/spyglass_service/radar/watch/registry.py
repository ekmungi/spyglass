"""The watch register: create, change and list the companies, labs and regulators followed."""

import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, ItemEntity, WatchEntity, dumps, loads, utcnow
from spyglass_service.radar.serialize import radar_items

KINDS = ("company", "lab", "regulator", "person", "publication")
STATUSES = ("active", "suggested", "muted")
# The kinds whose stories fill the brief's "On your watch list" section: what competitors and
# regulators are doing. AI labs, research centres and hospitals are kind "lab", and journals
# and societies "publication"; they are watched too, but their stories go to the ordinary
# sections. Discovery and the register both use "lab" for the AI-lab group.
WATCH_SECTION_KINDS = ("company", "regulator")
# The name of the group shown for entries that have no category.
OTHER = "Other"
# The look-back of the per-group "items this week" count.
WEEK = timedelta(days=7)
# How many recent linked items each entity shows on the watch page.
RECENT_PER_ENTITY = 3


class DuplicateEntity(ValueError):
    """Raised when a name (or alias) is already in the register."""


def norm_name(text: str) -> str:
    """Lower-case, punctuation-free, single-spaced form of a name, used for matching."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def entity_names(entity: WatchEntity) -> list[str]:
    """The entity's name followed by its aliases."""
    return [entity.name, *(loads(entity.aliases, []) or [])]


# Names this short, or written all in capitals (NICE, HAS, FDA, EMA), are matched with their
# exact capitals, so the English words "nice" and "has" never count as a mention.
_STRICT_MAX_LEN = 4


def _mention_pattern(name: str) -> re.Pattern[str]:
    """A whole-word pattern for one name; case-sensitive for short names and acronyms."""
    strict = len(name) <= _STRICT_MAX_LEN or (name.isupper() and any(c.isalpha() for c in name))
    flags = 0 if strict else re.IGNORECASE
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", flags)


def is_about(names: Iterable[str], *, title: str | None = None, headline: str | None = None,
             entities: Iterable[str] = ()) -> bool:
    """True when an item names a watched organisation, so the item is about it.

    Being found by an organisation's news search is not enough: a regulator's broad query
    returns general news. The item must name the organisation (its name or an alias) as a whole
    word in its title, its assessment headline, or the organisations its assessment lists.

    Args:
        names: The organisation's name and aliases.
        title: The item's title.
        headline: The assessment's rewritten headline.
        entities: The organisations named in the item (`Assessment.entities`).
    """
    texts = [t for t in (title, headline, *entities) if t]
    patterns = [_mention_pattern(n.strip()) for n in names if n and n.strip()]
    return any(p.search(text) for p in patterns for text in texts)


def item_is_about(entity: WatchEntity, title: str | None, assessment: Assessment | None) -> bool:
    """`is_about` for one stored item and its assessment (which may be missing)."""
    return is_about(
        entity_names(entity), title=title,
        headline=assessment.headline if assessment else None,
        entities=[str(e) for e in (loads(assessment.entities, []) or [])] if assessment else (),
    )


def entity_dict(entity: WatchEntity) -> dict:
    """The JSON shape of one register entry (without recent items)."""
    return {
        "id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "category": entity.category,
        "topic": entity.topic,
        "aliases": loads(entity.aliases, []) or [],
        "query": entity.query,
        "website": entity.website,
        "status": entity.status,
        "why": entity.why,
        "added_via": entity.added_via,
        "last_hit_at": entity.last_hit_at.isoformat() if entity.last_hit_at else None,
    }


def known_names(session: Session) -> set[str]:
    """Normalised names and aliases of every entity in the register, whatever its status."""
    return {norm_name(n) for e in session.exec(select(WatchEntity)).all() for n in entity_names(e)}


def create_entity(
    session: Session,
    name: str,
    *,
    kind: str = "company",
    category: str = "",
    status: str = "active",
    added_via: str = "user",
    aliases: Iterable[str] = (),
    query: str | None = None,
    why: str | None = None,
    topic: str | None = None,
    website: str | None = None,
) -> WatchEntity:
    """Add an entity. Raises DuplicateEntity when the name or an alias is already registered."""
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    taken = known_names(session)
    alias_list = [a.strip() for a in aliases if a and a.strip() and norm_name(a) != norm_name(name)]
    if any(norm_name(n) in taken for n in [name, *alias_list]):
        raise DuplicateEntity(f"{name} is already in the register")
    entity = WatchEntity(
        name=name, kind=kind, category=category.strip(), status=status, added_via=added_via,
        aliases=dumps(alias_list) if alias_list else None, query=query or f'"{name}"', why=why,
        topic=topic, website=website,
    )
    session.add(entity)
    try:
        session.commit()
    except IntegrityError as exc:  # unique name raced with another writer
        session.rollback()
        raise DuplicateEntity(f"{name} is already in the register") from exc
    session.refresh(entity)
    return entity


def update_entity(session: Session, entity_id: int, changes: dict) -> WatchEntity | None:
    """Apply the given fields to an entity; returns None when it does not exist.

    Only name, kind, category, status, aliases (a list), query, website and why can change.
    """
    entity = session.get(WatchEntity, entity_id)
    if entity is None:
        return None
    if "kind" in changes and changes["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if "status" in changes and changes["status"] not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    for field in ("name", "kind", "category", "status", "query", "website", "why"):
        if field in changes and changes[field] is not None:
            setattr(entity, field, changes[field].strip() if isinstance(changes[field], str) else changes[field])
    if "aliases" in changes and changes["aliases"] is not None:
        cleaned = [a.strip() for a in changes["aliases"] if a.strip()]
        entity.aliases = dumps(cleaned) if cleaned else None
    session.add(entity)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateEntity("another entity already has that name") from exc
    session.refresh(entity)
    return entity


def delete_entity(session: Session, entity_id: int) -> bool:
    """Remove an entity and its item links; returns False when it does not exist."""
    entity = session.get(WatchEntity, entity_id)
    if entity is None:
        return False
    for link in session.exec(select(ItemEntity).where(ItemEntity.entity_id == entity_id)).all():
        session.delete(link)
    session.delete(entity)
    session.commit()
    return True


def _recent_item_ids(session: Session, entities: list[WatchEntity]) -> dict[int, list[int]]:
    """Per entity, the ids of its newest linked items that are about it.

    Judged "out" items are skipped, and so are items the entity's search found that do not
    name it (`item_is_about`).
    """
    if not entities:
        return {}
    by_id = {e.id: e for e in entities}
    rows = session.exec(
        select(ItemEntity.entity_id, Item.id, Item.title, Item.published_at, Item.fetched_at,
               Assessment)
        .join(Item, Item.id == ItemEntity.item_id)
        .outerjoin(Assessment, Assessment.item_id == Item.id)
        .where(ItemEntity.entity_id.in_(list(by_id)))
        .where((Assessment.id.is_(None)) | (Assessment.tier != "out"))
    ).all()
    by_entity: dict[int, list[tuple]] = {}
    for entity_id, item_id, title, published, fetched, assessment in rows:
        if item_is_about(by_id[entity_id], title, assessment):
            by_entity.setdefault(entity_id, []).append((published or fetched, item_id))
    return {
        eid: [i for _, i in sorted(pairs, reverse=True)[:RECENT_PER_ENTITY]] for eid, pairs in by_entity.items()
    }


def _week_item_ids(session: Session, entity_ids: list[int], now: datetime | None) -> dict[int, set[int]]:
    """Per entity, the ids of items linked to it that were fetched in the last 7 days.

    One query for every entity. Items judged "out" are left out; an item that has not been judged
    yet still counts, because it is in the Feed. Counting is on fetch time, not publish time,
    because "what it brought into the Feed this week" is the question.
    """
    if not entity_ids:
        return {}
    cutoff = (now or utcnow().replace(tzinfo=None)) - WEEK
    rows = session.exec(
        select(ItemEntity.entity_id, ItemEntity.item_id)
        .join(Item, Item.id == ItemEntity.item_id)
        .outerjoin(Assessment, Assessment.item_id == Item.id)
        .where(ItemEntity.entity_id.in_(entity_ids), Item.fetched_at >= cutoff)
        .where((Assessment.id.is_(None)) | (Assessment.tier != "out"))
    ).all()
    found: dict[int, set[int]] = {}
    for entity_id, item_id in rows:
        found.setdefault(entity_id, set()).add(item_id)
    return found


def grouped(session: Session, *, now: datetime | None = None) -> dict:
    """The `GET /watch` payload: categories (by name) with entities and recent items, plus suggestions.

    Every entity carries `week_count` (items it brought into the Feed in the last 7 days), and
    every category carries the same for the whole group (an item found by two names counts once)
    and `paused`, true when every name in it is muted. `now` (naive UTC) is only for tests.
    """
    entities = session.exec(select(WatchEntity)).all()
    followed = [e for e in entities if e.status != "suggested"]
    recent_ids = _recent_item_ids(session, followed)
    week = _week_item_ids(session, [e.id for e in followed], now)
    items = {i["id"]: i for i in radar_items(session, [i for ids in recent_ids.values() for i in ids])}
    categories: dict[str, list[dict]] = {}
    group_items: dict[str, set[int]] = {}
    for e in sorted(followed, key=lambda x: x.name.lower()):
        name = e.category or OTHER
        entry = {
            **entity_dict(e),
            "week_count": len(week.get(e.id, ())),
            "recent": [items[i] for i in recent_ids.get(e.id, []) if i in items],
        }
        categories.setdefault(name, []).append(entry)
        group_items.setdefault(name, set()).update(week.get(e.id, ()))
    suggested = [entity_dict(e) for e in sorted(entities, key=lambda x: x.name.lower()) if e.status == "suggested"]
    return {
        "categories": [
            {
                "name": n,
                "entities": categories[n],
                "week_count": len(group_items[n]),
                "paused": all(e["status"] == "muted" for e in categories[n]),
            }
            for n in sorted(categories, key=str.lower)
        ],
        "suggested": suggested,
    }
