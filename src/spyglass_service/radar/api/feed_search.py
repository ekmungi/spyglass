"""Related items API: `GET /feed/related` and `GET /feed/items`.

Paths are relative to /api/radar. `/feed/related` gives the feed items close to a text or to
another item (exactly one of `text` and `item_id` is required): the usual RadarItem objects, each
with a `match` between 0 and 1, best first. `/feed/items?ids=` gives the items with those ids in
the order asked, which the Feed uses to show the items an assistant answer cited.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar import feed_search
from spyglass_service.radar.api.item_quality import infer_kinds
from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.radar.serialize import radar_items

logger = logging.getLogger(__name__)
router = APIRouter()

# Longest text accepted: a few words or a pasted sentence, not a document.
TEXT_MAX = 300
# Most ids `/feed/items` answers for in one request.
IDS_MAX = 50


def _index(request: Request):
    """The embedding index, or None when it cannot be built (text matching still works)."""
    state = getattr(request.app.state, "service_state", None)
    if state is None:
        return None
    try:
        return state.ensure_index()
    except Exception:  # noqa: BLE001 -- the index is optional; the answer degrades to text
        logger.exception("The embedding index is unavailable for related items")
        return None


@router.get("/feed/related", dependencies=[Depends(refuse_cross_site)])
def get_related(
    request: Request,
    text: str | None = Query(default=None, max_length=TEXT_MAX),
    item_id: int | None = None,
    limit: int = Query(40, ge=1, le=100),
) -> dict:
    """Feed items related to a text or to an item, with a `match` score each.

    Items judged "out" and items from switched-off feeds are left out. 422 unless exactly one of
    `text` and `item_id` is given; 404 for an unknown `item_id`.
    """
    query_text = " ".join((text or "").split())
    if (item_id is None) == (not query_text):
        raise HTTPException(status_code=422, detail="Give either text or item_id, not both.")
    index = _index(request)
    with Session(request.app.state.engine) as session:
        if item_id is not None:
            if session.get(Item, item_id) is None:
                raise HTTPException(status_code=404, detail="item not found")
            found = feed_search.related_to_item(
                session, index, item_id, limit=limit)
            shown = radar_items(session, [item_id])
            query: dict = {"item_id": item_id, "headline": shown[0]["headline"] if shown else ""}
        else:
            found = feed_search.related_items(
                session, index, query_text, limit=limit)
            query = {"text": query_text}
        scores = dict(found)
        items = infer_kinds(radar_items(session, [i for i, _ in found]))
    return {"items": [{**item, "match": scores[item["id"]]} for item in items], "query": query}


@router.get("/feed/items", dependencies=[Depends(refuse_cross_site)])
def get_feed_items(request: Request, ids: str = Query(max_length=600)) -> dict:
    """The items with the given ids (comma separated, at most 50), in the order given.

    Unknown ids are left out. 422 when `ids` holds anything but whole numbers.
    """
    try:
        wanted = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids must be whole numbers") from None
    if not wanted or len(wanted) > IDS_MAX or any(i <= 0 for i in wanted):
        raise HTTPException(status_code=422, detail=f"Give between 1 and {IDS_MAX} item ids.")
    with Session(request.app.state.engine) as session:
        return {"items": infer_kinds(radar_items(session, wanted))}
