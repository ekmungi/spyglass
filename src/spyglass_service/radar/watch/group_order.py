"""The order the watch page shows its groups in, kept in one stored document.

The document (RadarDoc key "watch_group_order") is a JSON list of group names. A group that is not
in the list follows after the listed ones, in alphabetical order, so an install that never orders
its groups sees the same alphabetical page as before.
"""

from collections.abc import Iterable

from sqlmodel import Session

from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow

ORDER_KEY = "watch_group_order"


def clean_order(names: Iterable[object]) -> list[str]:
    """The names as a list of distinct, non-empty strings in their given order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in names:
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            cleaned.append(name)
    return cleaned


def group_order(session: Session) -> list[str]:
    """The stored group order; empty when the reader never ordered the groups or the document is unreadable."""
    row = session.get(RadarDoc, ORDER_KEY)
    stored = loads(row.body if row else None, [])
    return clean_order(stored) if isinstance(stored, list) else []


def save_group_order(session: Session, names: Iterable[str], *, commit: bool = True) -> list[str]:
    """Store the group order and return it as stored.

    `commit=False` leaves the commit to the caller, so the order can change in the same
    transaction as the group change it belongs to.
    """
    cleaned = clean_order(names)
    row = session.get(RadarDoc, ORDER_KEY) or RadarDoc(key=ORDER_KEY, body="[]")
    row.body = dumps(cleaned)
    row.updated_at = utcnow()
    session.add(row)
    if commit:
        session.commit()
    return cleaned


def ordered(names: Iterable[str], stored: list[str]) -> list[str]:
    """The group names as the page shows them: those in `stored` first, in its order, then the rest A to Z."""
    present = set(names)
    first = [n for n in stored if n in present]
    listed = set(first)
    return [*first, *sorted((n for n in present if n not in listed), key=str.lower)]
