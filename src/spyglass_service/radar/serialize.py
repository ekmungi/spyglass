"""The one JSON shape of an item, shared by the feed, the brief, the watch page and the reader.

Every radar endpoint that returns items calls `radar_items`, so the frontend has a single
`RadarItem` type to render.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.assess_prompt import plain_title
from spyglass_service.radar.api.item_quality import address_kind
from spyglass_service.radar.filing_queue import queued_ids
from spyglass_service.radar.models import Assessment, ItemExtra, ItemState, ReaderDoc, loads
from spyglass_service.radar.profile_defaults import section_label
from spyglass_service.source_label import display_origin, user_feed_names


def _iso(value: datetime | None) -> str | None:
    """ISO-8601 text for a timestamp, or None."""
    return value.isoformat() if value else None


def signal_text(extra: dict) -> str | None:
    """A short human line for a community signal ("412 points on Hacker News"), or None."""
    if extra.get("points"):
        return f"{extra['points']} points on Hacker News"
    if extra.get("upvotes"):
        return f"{extra['upvotes']} community upvotes"
    return None


def _state_dict(state: ItemState | None) -> dict:
    """The reader-state block of a RadarItem; all-false defaults when no row exists."""
    return {
        "saved": bool(state and state.saved_at),
        "opened": bool(state and state.opened_at),
        "vote": state.vote if state else None,
        "from_user": bool(state and state.from_user),
        "captured_via": state.captured_via if state else None,
        "vault_path": state.vault_path if state else None,
    }


def radar_items(session: Session, item_ids: Iterable[int]) -> list[dict]:
    """Return the RadarItem dict for each id, in the order given; unknown ids are skipped.

    Reads the item, its assessment, reader state, extra facts, whether a reader document exists
    and whether the item waits in the filing queue, in six queries regardless of how many ids
    are asked for.
    """
    ids = list(dict.fromkeys(item_ids))
    if not ids:
        return []
    items = {i.id: i for i in session.exec(select(Item).where(Item.id.in_(ids))).all()}
    assessments = {
        a.item_id: a for a in session.exec(select(Assessment).where(Assessment.item_id.in_(ids))).all()
    }
    states = {
        s.item_id: s for s in session.exec(select(ItemState).where(ItemState.item_id.in_(ids))).all()
    }
    extras = {
        e.item_id: loads(e.data, {})
        for e in session.exec(select(ItemExtra).where(ItemExtra.item_id.in_(ids))).all()
    }
    readers = set(
        session.exec(
            select(ReaderDoc.item_id).where(ReaderDoc.item_id.in_(ids),
                                          ReaderDoc.status.in_(("ok", "partial")))
        ).all()
    )
    feed_names = user_feed_names(session)
    queued = queued_ids(session, ids)
    out: list[dict] = []
    for item_id in ids:
        item = items.get(item_id)
        if item is None:
            continue
        a = assessments.get(item_id)
        # A failed triage is not a judgement: it reads as unjudged, with no score and no reason.
        judged = a is not None and a.tier != "unjudged"
        extra = extras.get(item_id, {})
        section = a.section if a else ""
        out.append(
            {
                "id": item.id,
                # Some feeds put markup or entities in titles; the interface shows plain text.
                "title": plain_title(item.title),
                "headline": plain_title(a.headline if a and a.headline else item.title),
                "url": item.url,
                "source": item.source,
                "origin": extra.get("publisher") or display_origin(item, feed_names),
                "published_at": _iso(item.published_at),
                "fetched_at": _iso(item.fetched_at),
                "kind": a.kind if a else (address_kind(item.url) or "news"),
                "section": section,
                "section_label": section_label(session, section),
                "tier": a.tier if judged else "unjudged",
                "score": a.score if judged else None,
                "why": a.why if judged else None,
                "key_points": loads(a.key_points, []) if a else [],
                "entities": loads(a.entities, []) if a else [],
                "signal": signal_text(extra),
                # Where the reader's own Claude session filed the item ({path, project, at}).
                "filed": extra.get("filed") if isinstance(extra.get("filed"), dict) else None,
                # "waiting" while the item is in the "To file" queue, else None.
                "filing": "waiting" if item_id in queued else None,
                "state": _state_dict(states.get(item_id)),
                "has_reader": item_id in readers,
            }
        )
    return out
