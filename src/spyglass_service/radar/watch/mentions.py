"""Count which organisations the assessed news names, for the watch suggestions and the watch review.

Both callers count the same way, so the review's list of new names and the page's suggestions
follow one rule: distinct items per normalised name inside a time window, split by the item's
profile section, with each name as most often written.
"""

from collections import Counter
from datetime import datetime

from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, loads
from spyglass_service.radar.watch.registry import norm_name

# Shorter normalised names are initials or noise, and are not counted.
MIN_KEY = 3


def count_mentions(session: Session, cutoff: datetime, *, tiers: tuple[str, ...] | None = None,
                   sections: list[str] | None = None) -> tuple[dict[str, dict[str, set[int]]], dict[str, str]]:
    """Who the news names: `{name: {section: item ids}}` and each name as most often written.

    Counts the organisations an item's assessment lists (`Assessment.entities`) for items published
    (else fetched) at or after `cutoff` (naive UTC). Names are keyed by `norm_name`.

    Args:
        session: An open database session.
        cutoff: The start of the window.
        tiers: Count only items of these tiers; None counts every tier except "out".
        sections: Count only items in these profile sections; None counts every section.
    """
    query = (
        select(Assessment.item_id, Assessment.entities, Assessment.section, Item.published_at, Item.fetched_at)
        .join(Item, Item.id == Assessment.item_id)
        .where(Assessment.entities.is_not(None))
        .where(Assessment.tier.in_(tiers) if tiers is not None else Assessment.tier != "out")
    )
    if sections is not None:
        query = query.where(Assessment.section.in_(sections))
    items: dict[str, dict[str, set[int]]] = {}
    forms: dict[str, Counter] = {}
    for item_id, raw, section, published, fetched in session.exec(query).all():
        names = loads(raw, [])
        if (published or fetched) < cutoff or not isinstance(names, list):
            continue
        for name in names:
            key = norm_name(str(name))
            if len(key) >= MIN_KEY:
                items.setdefault(key, {}).setdefault(section, set()).add(item_id)
                forms.setdefault(key, Counter())[str(name).strip()] += 1
    return items, {key: counter.most_common(1)[0][0] for key, counter in forms.items()}
