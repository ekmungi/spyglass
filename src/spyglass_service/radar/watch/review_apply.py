"""Apply the review proposals the reader ticked, all in one transaction.

Nothing here decides anything: it does exactly what it is given and reports what changed. Ids
that no longer exist and names already in the register are skipped without an error, because the
register may have changed since the review was made. A bad group name refuses the whole request
before anything changes.
"""

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.models import WatchEntity
from spyglass_service.radar.watch.groups import clean_category, delete_with_links, members
from spyglass_service.radar.watch.registry import KINDS, entity_names, norm_name


def _checked(selection: dict) -> dict:
    """The selection with every destination group name validated (GroupError otherwise)."""
    return {
        "regroup": [{"id": r["id"], "to": clean_category(r["to"])} for r in selection.get("regroup") or []],
        "merge_groups": [
            {"from": str(m["from"]), "to": clean_category(m["to"])} for m in selection.get("merge_groups") or []
        ],
        "categories_added": [clean_category(a.get("category") or "Other") for a in selection.get("add") or []],
    }


def apply_review(engine: Engine, selection: dict) -> dict:
    """Apply a ticked selection: `pause`, `remove` (id lists), `regroup`, `merge_groups`, `add`.

    Order: removals, pauses, regroups, merges, additions. Returns `applied` (counts of paused,
    removed, added, regrouped and merged names) and `removed`, the removed entries with their
    links for the interface's Undo (`groups.restore_entries`). Raises GroupError before changing
    anything when a destination group name is not valid.
    """
    checked = _checked(selection)
    applied = {"paused": 0, "removed": 0, "added": 0, "regrouped": 0, "merged": 0}
    removed: list[dict] = []
    with Session(engine) as session:
        for entity_id in selection.get("remove") or []:
            entity = session.get(WatchEntity, entity_id)
            if entity is not None:
                removed.append(delete_with_links(session, entity))
        for entity_id in selection.get("pause") or []:
            entity = session.get(WatchEntity, entity_id)
            if entity is not None and entity.status == "active":
                entity.status = "muted"
                session.add(entity)
                applied["paused"] += 1
        for change in checked["regroup"]:
            entity = session.get(WatchEntity, change["id"])
            if entity is not None:
                entity.category = change["to"]
                session.add(entity)
                applied["regrouped"] += 1
        for merge in checked["merge_groups"]:
            for entity in members(session, merge["from"], followed_only=False):
                entity.category = merge["to"]
                session.add(entity)
                applied["merged"] += 1
        applied["added"] = _add_all(session, selection.get("add") or [], checked["categories_added"])
        session.commit()
    applied["removed"] = len(removed)
    return {"applied": applied, "removed": removed}


def _add_all(session: Session, entries: list[dict], categories: list[str]) -> int:
    """Create the ticked additions as followed names, skipping any already in the register."""
    taken = {norm_name(n) for e in session.exec(select(WatchEntity)).all() for n in entity_names(e)}
    added = 0
    for raw, category in zip(entries, categories, strict=True):
        name = " ".join(str(raw.get("name") or "").split())
        if not name or norm_name(name) in taken:
            continue
        taken.add(norm_name(name))
        session.add(WatchEntity(
            name=name, kind=raw.get("kind") if raw.get("kind") in KINDS else "company", category=category,
            status="active", added_via="discovered", why=(raw.get("why") or None),
            query=(raw.get("query") or "").strip() or f'"{name}"',
        ))
        added += 1
    return added
