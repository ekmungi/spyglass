# src/spyglass_service/api_pages.py
"""Manual page capture REST API: add any web page as an item + card.

POST /api/pages canonicalizes the URL, dedupes against existing items (the same page
never becomes two cards), otherwise creates Item(source='manual') + Card and runs the
enrichment cascade gate-free (an explicit user add is never throttled by Gate 1).
Both network steps -- page title and enrichment -- are best-effort: their failure
never fails the request, because the card already exists.
"""

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from spyglass_service.api_cards import _serialize
from spyglass_service.source_label import user_feed_names
from spyglass_service.documents import fetch_page_title, normalize_url
from spyglass_service.enrich import enrich_item
from spyglass_service.models import Card, CardState, Item

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class PageCreate(BaseModel):
    """Body: the page URL the user wants captured as a card."""

    url: str


def _find_existing(session: Session, url: str, canonical: str) -> Item | None:
    """The already-collected item for this page, matched on either identity column.

    Both the raw and canonical URL forms are checked against both columns: collectors
    store the raw form in `url`, while manual items key `external_id` on the canonical
    form — comparing only one form against one column would let the same page in twice
    (or miss a legitimate duplicate) whenever normalization changes the string.

    Args:
        session: Active session.
        url: The URL exactly as posted.
        canonical: Its normalize_url form.

    Returns:
        The matching Item, or None when the page is new.
    """
    forms = {url, canonical}
    return session.exec(
        select(Item).where(
            or_(Item.external_id.in_(forms), Item.url.in_(forms))  # type: ignore[attr-defined]
        )
    ).first()


def _ensure_card(session: Session, item: Item) -> Card:
    """The item's card, creating a bare one for the (edge-case) card-less item.

    Args:
        session: Active session (committed here when a card is created).
        item: The existing item being returned as a dedupe hit.

    Returns:
        The item's Card, freshly created if it had none.
    """
    card = session.exec(select(Card).where(Card.item_id == item.id)).first()
    if card is None:
        card = Card(item_id=item.id, state=CardState.NEW, curated=False, summary="")
        session.add(card)
        session.commit()
        session.refresh(card)
    return card


def _safe_title(url: str) -> str:
    """The page's own title, falling back to the URL on any failure.

    fetch_page_title already returns None on HTTP errors; the except covers anything
    unexpected (extractor bugs, DNS explosions) -- a title is cosmetic, never fatal.

    Args:
        url: The original posted URL (no canonical rewrite; the abs page titles better).

    Returns:
        A non-empty title string.
    """
    try:
        return fetch_page_title(url) or url
    except Exception:  # noqa: BLE001 -- the title is best-effort by contract
        logger.exception("page title fetch failed for %s; using the url as title", url)
        return url


@router.post("/pages")
async def add_page(request: Request, body: PageCreate) -> dict:
    """Capture a web page as a manual item + card, enriched gate-free.

    400 for non-http(s) URLs. A page already collected (by canonical external_id or
    stored url) returns its existing card as {..., "status": "exists"} -- no re-fetch,
    no re-enrichment. Otherwise the item + card are committed first, then the title
    fetch's card is enriched via the enrichment cascade with bypass_gate=True; an enrichment
    failure is logged and the (un-enriched) card still returns as "created".
    """
    url = body.url
    if urlparse(url).scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="only http/https URLs can be added")
    canonical = normalize_url(url)
    engine = request.app.state.engine

    with Session(engine) as session:
        existing = _find_existing(session, url, canonical)
        if existing is not None:
            card = _ensure_card(session, existing)
            return {**_serialize(card, existing, names=user_feed_names(session)), "status": "exists"}

    # Blocking network call (title) runs in the threadpool, outside any DB session.
    title = await run_in_threadpool(_safe_title, url)
    try:
        with Session(engine) as session:
            item = Item(
                source="manual", external_id=canonical, url=url,
                origin=urlparse(url).netloc or None, title=title,
                published_at=None, feed_url=None,
            )
            session.add(item)
            session.flush()
            card = Card(item_id=item.id, state=CardState.NEW, curated=False, summary="")
            session.add(card)
            session.commit()
            card_id, item_id = card.id, item.id
    except IntegrityError:
        # Two rapid adds of the same page raced past the dedupe read; the UNIQUE
        # (source, external_id) constraint caught the second one — answer it honestly
        # as the existing page instead of a 500.
        with Session(engine) as session:
            existing = _find_existing(session, url, canonical)
            if existing is None:
                raise  # constraint hit for some other reason; surface it
            card = _ensure_card(session, existing)
            return {**_serialize(card, existing, names=user_feed_names(session)), "status": "exists"}

    # Enrichment (fetch + LLM + embed) is best-effort: the card already exists, so a
    # failure here must never turn the successful add into an error response.
    settings = request.app.state.settings
    index = request.app.state.service_state.ensure_index()
    try:
        await run_in_threadpool(
            enrich_item, engine, index, settings, card_id, bypass_gate=True
        )
    except Exception:  # noqa: BLE001 -- enrichment is an enhancement, not the add itself
        logger.exception("enrichment failed for manually added page card %s", card_id)

    # Re-read after enrichment so the response carries the summary/relevance it wrote.
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, item_id)
        return {**_serialize(card, item), "status": "created"}
