"""Cards REST API: list, filter, and update triage cards for the dashboard."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import frontmatter
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, select

from spyglass_service.autocategorize import confirm_category, needs_review
from spyglass_service.feedback import set_feedback
from spyglass_service.lifecycle import delete_cards
from spyglass_service.models import Card, CardState, Feed, Item
from spyglass_service.relevance_serve import effective_relevance_map
from spyglass_service.source_label import display_origin, user_feed_names

router = APIRouter(prefix="/api")

# Sentinel so _serialize can tell "no effective level computed" (fall back to the stored value)
# apart from an explicit None, which is the valid "unjudged" effective relevance.
_UNSET = object()


class CardUpdate(BaseModel):
    """Patch body: any subset of state, note, and the custom deep-dive prompt."""

    state: CardState | None = None
    note: str | None = None
    deep_dive_prompt: str | None = None


class FeedbackPatch(BaseModel):
    """Body for setting/clearing a card's thumbs feedback: up / down / null."""

    feedback: str | None = None


def _serialize(
    card: Card, item: Item, effective: object = _UNSET, names: Mapping[str, str] | None = None
) -> dict:
    """Flatten a card and its item into the shape the dashboard renders.

    names: feed address -> the name the user set in the Feeds tab (source_label.user_feed_names).
    When the item's feed has one, `origin` carries that name instead of the feed's stored title;
    callers that omit it get the stored origin.

    The centroid tier/recommendations are retired; category_tier and
    category_recommendations are kept as null/empty so the frontend contract holds.

    effective: the card's blended effective relevance, or None when unjudged.
    Left as _UNSET by single-card callers (mutation responses), where it falls back to the
    stored relevance -- the list endpoint computes and passes the real blended value.

    All values MUST stay JSON-native (datetimes .isoformat()'d, enums .value'd): GET /api/cards
    serializes these dicts with json.dumps directly, bypassing FastAPI's jsonable_encoder,
    so a raw datetime/Decimal added here would raise at request time.
    """
    return {
        "id": card.id,
        "state": card.state.value,
        "curated": card.curated,
        "summary": card.summary,
        "tags": card.tags.split(",") if card.tags else [],
        "category": card.category,
        "group": card.group_label,
        "relevance": card.relevance,
        # Displayed/filterable relevance: explicit label -> blended score -> null when unjudged.
        "effective_relevance": card.relevance if effective is _UNSET else effective,
        "relevance_ai": card.relevance_ai,
        "relevance_reason": card.relevance_reason,
        "relevance_override": card.relevance_override,
        "feedback": card.feedback,
        "feedback_at": card.feedback_at.isoformat() if card.feedback_at else None,
        "category_ai": card.category_ai,
        "category_override": card.category_override,
        "source_tags": item.source_tags.split(",") if item.source_tags else [],
        "note": card.note,
        "deep_dive_prompt": card.deep_dive_prompt,
        "briefing_path": card.briefing_path,
        "created_at": card.created_at.isoformat(),
        "updated_at": card.updated_at.isoformat(),
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "origin": display_origin(item, names or {}),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "category_tier": None,
        "category_recommendations": [],
    }


# Characters of summary kept in the list payload -- enough to fill the list row's 2-line snippet
# (ListPane clamps to 2 lines); the reader fetches the full summary on open.
_LEAN_SUMMARY_CHARS = 280


def _serialize_lean(
    card: Card, item: Item, effective: object = _UNSET, names: Mapping[str, str] | None = None
) -> dict:
    """The list-row shape: the full serialization with `summary` truncated to a short preview.

    The list only renders a 2-line summary snippet, yet full summaries dominate the /api/cards
    payload. Ship only a preview here; the reader fetches the full card (incl.
    the complete summary) on open via GET /api/cards/{id}. Returns a new dict (no mutation).
    """
    row = _serialize(card, item, effective, names)
    preview = row["summary"][:_LEAN_SUMMARY_CHARS] if row["summary"] else row["summary"]
    return {**row, "summary": preview}


@router.get("/cards")
def list_cards(request: Request, state: CardState | None = None, source: str | None = None):
    """List cards joined with their items, newest first.

    Without an explicit state filter, dismissed cards stay hidden: dismissed
    means archived, recoverable via state=dismissed, never deleted.
    """
    with Session(request.app.state.engine) as session:
        # Null-tolerant feed filter: LEFT JOIN Feed on Item.feed_url
        # so items with null feed_url (Raindrop/legacy) land with Feed.id == None
        # and are kept. Only items whose feed is explicitly disabled are excluded.
        statement = (
            select(Card, Item)
            .join(Item, Card.item_id == Item.id)
            .outerjoin(Feed, Item.feed_url == Feed.feed_url)
            .where(or_(Feed.enabled == True, Feed.id == None))  # noqa: E711, E712
        )
        if state is not None:
            statement = statement.where(Card.state == state)
        else:
            statement = statement.where(Card.state != CardState.DISMISSED)
        if source is not None:
            statement = statement.where(Item.source == source)
        statement = statement.order_by(Card.created_at.desc())  # type: ignore[attr-defined]
        rows = session.exec(statement).all()
        names = user_feed_names(session)  # one small query over the feed table, not per card
        # Blended effective relevance per card: LLM prior nudged by semantic k-NN to the user's
        # thumbs. Computed batch-wise off the in-memory index; falls back to the
        # stored bucket when a card has no vector or there are no thumbs.
        index = request.app.state.service_state.ensure_index()
        effective = effective_relevance_map(request.app.state.engine, index, rows)
        rows_out = [_serialize_lean(card, item, effective[card.id], names) for card, item in rows]
        # Pre-serialize so FastAPI's jsonable_encoder does not re-walk every row (the largest
        # measured layer when profiling the slow card list); the dicts are already JSON-native.
        return Response(content=json.dumps(rows_out), media_type="application/json")


def _serialize_one(request: Request, card_id: int) -> dict | None:
    """Serialize one card (full shape) with its blended effective relevance, or None if unknown.

    Reuses the list endpoint's effective-relevance computation for a single row so a card fetched
    on its own (reader open, feedback response) shows the same displayed level it has in the list.
    """
    engine = request.app.state.engine
    with Session(engine) as session:
        row = session.exec(
            select(Card, Item).where(Card.item_id == Item.id).where(Card.id == card_id)
        ).first()
        names = user_feed_names(session)
    if row is None:
        return None
    index = request.app.state.service_state.ensure_index()
    effective = effective_relevance_map(engine, index, [row])
    return _serialize(row[0], row[1], effective[row[0].id], names)


@router.get("/cards/{card_id}/briefing")
def read_briefing(request: Request, card_id: int):
    """Return a finished card's briefing markdown for in-dashboard rendering.

    Only files inside the configured vault are served (traversal protection).
    """
    settings = request.app.state.settings
    with Session(request.app.state.engine) as session:
        card = session.get(Card, card_id)
    if card is None or not card.briefing_path:
        raise HTTPException(status_code=404, detail="no briefing for this card")
    briefing = Path(card.briefing_path).resolve()
    vault = settings.vault_path.resolve() if settings.vault_path else None
    if vault is None or vault not in briefing.parents:
        raise HTTPException(status_code=403, detail="briefing outside the vault")
    if not briefing.is_file():
        raise HTTPException(status_code=404, detail="briefing file missing")
    # The note's properties block is for Obsidian; the dashboard shows the body.
    text = briefing.read_text(encoding="utf-8")
    try:
        body = frontmatter.loads(text).content
    except Exception:  # noqa: BLE001 -- a malformed block is shown as written, not lost
        body = text
    return {"markdown": body}


# Similar-articles endpoint bounds: default breadth and the hard cap that
# keeps one request from serializing the whole corpus.
_SIMILAR_DEFAULT_K = 20
_SIMILAR_MAX_K = 50


@router.get("/cards/{card_id}/similar")
def similar_cards(request: Request, card_id: int, k: int = _SIMILAR_DEFAULT_K) -> list[dict]:
    """Articles most similar to this one, by embedding cosine.

    Each result is the serialized card plus 'score': the cosine clamped to 0..1 and
    rounded to 4dp, ranked best-first. The seed card is excluded; embedded items
    without a card (or dismissed) are skipped. 404 for an unknown card; a seed with
    no vector yet returns [] rather than erroring.
    """
    # Clamp into [1, MAX]: a negative/zero k would make index.similar stop immediately
    # (len(out) >= k true at once), silently returning a single result instead of a page.
    k = max(1, min(k, _SIMILAR_MAX_K))
    engine = request.app.state.engine
    index = request.app.state.service_state.ensure_index()
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")
        if not index.has(card.item_id):
            return []  # not embedded yet: honest empty result, never a crash
        out: list[dict] = []
        names = user_feed_names(session)
        for item_id, score in index.similar(card.item_id, k=k):
            row = session.exec(
                select(Card, Item)
                .where(Card.item_id == Item.id)
                .where(Item.id == item_id)
                .where(Card.state != CardState.DISMISSED)
            ).first()
            if row is not None:
                # Cosine is mathematically -1..1; negatives carry no 'similarity' meaning
                # for display, so the wire contract clamps to 0..1.
                out.append({**_serialize(row[0], row[1], names=names),
                            "score": round(max(0.0, min(1.0, score)), 4)})
        return out


@router.patch("/cards/{card_id}")
def update_card(request: Request, card_id: int, update: CardUpdate):
    """Apply a partial update to one card; unknown ids are a 404."""
    with Session(request.app.state.engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")
        if update.state is not None:
            card.state = update.state
        if update.note is not None:
            card.note = update.note
        if update.deep_dive_prompt is not None:
            card.deep_dive_prompt = update.deep_dive_prompt
        card.updated_at = datetime.now(UTC)
        session.add(card)
        session.commit()
        session.refresh(card)
        item = session.get(Item, card.item_id)
        return _serialize(card, item, names=user_feed_names(session))


@router.patch("/cards/{card_id}/feedback")
def patch_card_feedback(request: Request, card_id: int, body: FeedbackPatch) -> dict:
    """Set or clear a card's thumbs feedback (up/down/null). Returns the full updated card.

    404 if unknown, 422 for a value other than up/down/null. Feedback is a quiet learning signal: it
    never changes the card's state or visibility. Returning the full card -- incl. a thumb-down's
    'out' pin and the blended effective relevance -- lets the client merge the change in place
    instead of reloading the whole list. The full card is a superset of the old
    {feedback, feedback_at} shape, so existing readers of those two keys keep working.
    """
    try:
        result = set_feedback(request.app.state.engine, card_id, body.feedback)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    card = _serialize_one(request, card_id)
    if card is None:  # set_feedback just confirmed the card exists; defensive only
        raise HTTPException(status_code=404, detail="card not found")
    return card


@router.delete("/cards/{card_id}")
def delete_card(request: Request, card_id: int) -> dict:
    """Permanently delete one card (+ its content, highlights, item) and tombstone it.

    Raindrop items move to the Processed collection. Returns 404 when the card does
    not exist.
    """
    result = delete_cards(
        request.app.state.engine,
        request.app.state.settings,
        [card_id],
        index=request.app.state.service_state.ensure_index(),
    )
    if result["deleted"] == 0:
        raise HTTPException(status_code=404, detail="card not found")
    return result


@router.get("/cards/needs-review")
def cards_needs_review(request: Request) -> list[dict]:
    """Uncategorized cards awaiting a human category (the LLM 'doesn't fit' tail)."""
    return needs_review(request.app.state.engine)


@router.get("/review-count")
def review_count(request: Request) -> dict:
    """Count of items awaiting category review (drives the chip badge + session reminder)."""
    return {"needs_review": len(needs_review(request.app.state.engine))}


@router.post("/cards/{card_id}/confirm-category")
def confirm_card_category(request: Request, card_id: int, body: dict | None = None) -> dict:
    """Confirm a card's current category; optionally change it too (a human spot-check).

    Optional body: {"category": "<new_category>"} to also change the category. Returns
    {category, category_confirmed, category_override}. 404 when the card is not found.
    """
    result = confirm_category(
        request.app.state.engine, card_id, (body or {}).get("category"),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return result


@router.post("/cards/{card_id}/open-external")
def open_external(request: Request, card_id: int) -> dict:
    """Open this card's link in the host's default browser.

    Keyed by card_id (never an arbitrary URL) and limited to http/https schemes.
    Returns 404 when the card is unknown, 400 for a non-web scheme (e.g. file://).
    The opener is injected via app.state.open_external so tests never call the real
    webbrowser module.
    """
    with Session(request.app.state.engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")
        item = session.get(Item, card.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="card not found")
    url: str = item.url
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="unsupported url scheme")
    request.app.state.open_external(url)
    return {"opened": True, "url": url}


@router.get("/cards/{card_id}")
def get_card(request: Request, card_id: int) -> dict:
    """Return one card in full (incl. summary + blended effective relevance) for the reader.

    The list endpoint ships a lean row without the full summary; the reader fetches the
    complete card here on open. 404 for an unknown card.
    """
    result = _serialize_one(request, card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return result
