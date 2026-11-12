"""Whole-group changes to the watch register: pause, resume, rename, move and remove, and undo.

A group is every register entry that shares a category. Each action changes all of a group's
entries in one transaction, so a failure leaves the group as it was. Removing returns the removed
entries, links included, so the interface can offer "Undo" by sending them back to
`restore_entries`.
"""

import re
from datetime import datetime

from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import ItemEntity, WatchEntity, dumps
from spyglass_service.radar.watch.registry import OTHER, STATUSES, entity_dict, norm_name

ACTIONS = ("pause", "resume", "rename", "move", "remove")
# Longest group name accepted; the register shows names as headings.
MAX_CATEGORY = 60
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class GroupError(ValueError):
    """The request is not acceptable; the message is fit to show the reader."""


class GroupNotFound(LookupError):
    """No followed entry has this category."""


def clean_category(value: object) -> str:
    """A group name as stored: one line, trimmed, at most 60 characters; "Other" means no category.

    Raises GroupError with a readable message otherwise.
    """
    if not isinstance(value, str) or _CONTROL.search(value):
        raise GroupError("A group name must be a single line of text.")
    text = " ".join(value.split())
    if not text:
        raise GroupError("Give the group a name.")
    if len(text) > MAX_CATEGORY:
        raise GroupError(f"A group name can be at most {MAX_CATEGORY} characters.")
    return "" if text.casefold() == OTHER.casefold() else text


def members(session: Session, category: str, *, followed_only: bool) -> list[WatchEntity]:
    """The entries of a group; "Other" is the entries with no category."""
    stored = "" if category.casefold() == OTHER.casefold() else category
    rows = session.exec(select(WatchEntity).where(WatchEntity.category == stored)).all()
    return [e for e in rows if e.status != "suggested"] if followed_only else list(rows)


def _links(session: Session, entity_id: int) -> list[dict]:
    """The item links of one entity as `{"item_id", "via"}`."""
    rows = session.exec(select(ItemEntity).where(ItemEntity.entity_id == entity_id)).all()
    return [{"item_id": r.item_id, "via": r.via} for r in rows]


def delete_with_links(session: Session, entity: WatchEntity) -> dict:
    """Delete one entry and its item links without committing; returns it for undo.

    The result is `entity_dict` plus `links`, the shape `restore_entries` takes back.
    """
    removed = {**entity_dict(entity), "links": _links(session, entity.id)}
    for link in session.exec(select(ItemEntity).where(ItemEntity.entity_id == entity.id)).all():
        session.delete(link)
    session.delete(entity)
    return removed


def apply_group_action(session: Session, category: str, action: str, *, to: str | None = None) -> list[dict]:
    """Do one action on every entry of a group and commit once.

    pause: active entries become muted (suggestions are left for the reader to decide).
    resume: muted entries become active. rename and move: every entry, suggestions included,
    takes the new category (naming an existing group merges into it). remove: followed entries
    are deleted with their links.

    Returns the removed entries for "remove" (each as `entity_dict` plus `links`), else [].
    Raises GroupError for an unknown action or a bad or missing `to`, GroupNotFound when the
    group has no entries.
    """
    if action not in ACTIONS:
        raise GroupError(f"The action must be one of: {', '.join(ACTIONS)}.")
    target = clean_category(to) if action in ("rename", "move") and to is not None else None
    if action in ("rename", "move") and to is None:
        raise GroupError("Say which group to move them to.")
    group = members(session, category, followed_only=action in ("pause", "resume", "remove"))
    if not group:
        raise GroupNotFound(f"There is no group called {category}.")
    removed: list[dict] = []
    for entity in group:
        if action == "pause" and entity.status == "active":
            entity.status = "muted"
        elif action == "resume" and entity.status == "muted":
            entity.status = "active"
        elif target is not None:
            entity.category = target
        elif action == "remove":
            removed.append(delete_with_links(session, entity))
            continue
        session.add(entity)
    session.commit()
    return removed


def restore_entries(session: Session, entries: list[dict]) -> int:
    """Re-create entries removed by `apply_group_action`, with their links to items that still exist.

    An entry whose name is already in the register is skipped. Returns how many were restored.
    """
    taken = {norm_name(e.name) for e in session.exec(select(WatchEntity)).all()}
    existing_items = set(session.exec(select(Item.id)).all())
    restored = 0
    for raw in entries:
        name = str(raw.get("name") or "").strip()
        if not name or norm_name(name) in taken:
            continue
        status = raw.get("status") if raw.get("status") in STATUSES else "active"
        entity = WatchEntity(
            name=name, kind=raw.get("kind") or "company", category=raw.get("category") or "",
            topic=raw.get("topic"), aliases=_aliases(raw), query=raw.get("query") or f'"{name}"',
            website=raw.get("website"), status=status, why=raw.get("why"),
            added_via=raw.get("added_via") or "user",
            last_hit_at=_when(raw.get("last_hit_at")),
        )
        session.add(entity)
        session.flush()
        taken.add(norm_name(name))
        for link in raw.get("links") or []:
            if link.get("item_id") in existing_items:
                session.add(ItemEntity(item_id=link["item_id"], entity_id=entity.id, via=link.get("via") or "query"))
        restored += 1
    session.commit()
    return restored


def _aliases(raw: dict) -> str | None:
    """The aliases of a restored entry as the stored JSON text (None when there are none)."""
    aliases = [str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip()]
    return dumps(aliases) if aliases else None


def _when(value: object) -> datetime | None:
    """A stored timestamp parsed back from its ISO text (naive UTC); None when absent or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None
