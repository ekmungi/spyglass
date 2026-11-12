"""The WHERE conditions of a GET /feed request (everything except the paging cursor and the order).

Kept apart from the route so `radar/api/items.py` stays small. The rules: items from disabled
feeds are hidden; the default view also hides tier "out" and unjudged items older than two days;
anything the reader kept, sent in or filed, a text search, a tier choice or a saved view
(`radar/feed_views.py`) replaces the default quality rules.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.exc import OperationalError

from spyglass_service.content_store import search_fulltext
from spyglass_service.models import Feed, Item
from spyglass_service.radar.api.item_quality import kind_condition
from spyglass_service.radar.filed import filed_condition
from spyglass_service.radar.filing_queue import waiting_condition
from spyglass_service.radar.models import Assessment, ItemState, utcnow

logger = logging.getLogger(__name__)

# The default feed hides items nobody has judged once they are older than this.
UNJUDGED_MAX_AGE = timedelta(days=2)
_VISIBLE_TIERS = ("top", "notable", "skim")


def _naive_utc(value: datetime) -> datetime:
    """Timestamp as the naive UTC the database stores."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def title_like(q: str) -> str:
    """A LIKE pattern matching `q` anywhere, with the LIKE wildcards escaped."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_ids(engine, q: str) -> list[int]:
    """Item ids whose stored text (full-text search) matches `q`; [] when search fails."""
    try:
        return [h["item_id"] for h in search_fulltext(engine, q.replace('"', " "), limit=500)]
    except OperationalError:
        logger.warning("full-text search failed for query %r; using title match only", q)
        return []


def feed_conditions(
    *, section: str | None, kind: str | None, tier: str | None, saved: bool | None,
    from_user: bool | None, q: str | None, engine, sort_key, filed: bool | None = None,
    waiting: bool = False, extra: tuple = (),
) -> list:
    """The WHERE conditions of a feed request (everything except the paging cursor).

    `extra` are the terms of a saved view; a view brings its own quality rules.
    """
    conds: list = [or_(Item.feed_url.is_(None), Feed.id.is_(None), Feed.enabled == True)]  # noqa: E712
    if section:
        conds.append(Assessment.section == section)
    if kind:
        conds.append(kind_condition(kind))
    if saved is True:
        conds.append(ItemState.saved_at.is_not(None))
    elif saved is False:
        conds.append(ItemState.saved_at.is_(None))
    if from_user is True:
        conds.append(ItemState.from_user == True)  # noqa: E712
    if filed is True:
        conds.append(filed_condition())
    if waiting:
        conds.append(waiting_condition())
    conds.extend(extra)
    if q and q.strip():
        ids = search_ids(engine, q.strip())
        conds.append(or_(Item.id.in_(ids), Item.title.ilike(title_like(q.strip()), escape="\\")))
    if tier == "all":
        return conds
    if tier == "unjudged":
        # No judgement at all, or one that failed and is waiting to be retried.
        conds.append(or_(Assessment.id.is_(None), Assessment.tier == "unjudged"))
    elif tier:
        conds.append(Assessment.tier == tier)
    elif saved is True or from_user is True or filed is True or waiting or extra:
        pass  # something the reader kept or sent in is never hidden by the quality rules
    elif q and q.strip():
        conds.append(or_(Assessment.id.is_(None), Assessment.tier != "out"))
    else:
        cutoff = _naive_utc(utcnow() - UNJUDGED_MAX_AGE)
        conds.append(or_(
            Assessment.tier.in_(_VISIBLE_TIERS),
            and_(Assessment.id.is_(None), sort_key >= cutoff),
        ))
    return conds
