"""Search + full-text REST endpoints: stored article content for the dashboard."""

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import Session, select

from spyglass_service.api_cards import _serialize
from spyglass_service.content_store import get_fulltext, search_fulltext
from spyglass_service.fetch_queue import active_card_ids, enqueue, job_for_card
from spyglass_service.models import Card, FetchJob, Item
from spyglass_service.source_label import user_feed_names

router = APIRouter(prefix="/api")


@router.get("/search")
def search(request: Request, q: str = "") -> list[dict]:
    """Full-text search across stored article markdown, with title/summary fallback.

    Returns matching cards (joined with their item) plus a `snippet` showing where the
    match occurred, ordered by relevance. An empty query returns an empty list.
    """
    engine = request.app.state.engine
    hits = search_fulltext(engine, q)
    if not hits:
        return []
    item_ids = [h["item_id"] for h in hits]
    with Session(engine) as session:
        rows = session.exec(
            select(Card, Item).where(Card.item_id == Item.id).where(Item.id.in_(item_ids))
        ).all()
        names = user_feed_names(session)
    by_item = {item.id: (card, item) for card, item in rows}
    results: list[dict] = []
    for hit in hits:
        pair = by_item.get(hit["item_id"])
        if pair is None:
            continue  # item has no card yet; skip rather than guess
        card, item = pair
        results.append({**_serialize(card, item, names=names), "snippet": hit["snippet"]})
    return results


@router.get("/cards/{card_id}/fulltext")
def read_card_fulltext(request: Request, card_id: int) -> dict:
    """Return a card's stored full-text markdown for the reader.

    status 'absent' (markdown null) when nothing is stored yet; 404 for unknown cards.
    """
    engine = request.app.state.engine
    with Session(engine) as session:
        card = session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    stored = get_fulltext(engine, card.item_id)
    body = stored if stored is not None else {"status": "absent", "markdown": None}
    # The job rides along so a freshly-mounted reader can render "fetching"
    # without having survived the navigation that destroyed the previous pane.
    return {**body, "job": _job_payload(job_for_card(engine, card_id))}


def _job_payload(job: FetchJob | None) -> dict | None:
    """Serialize a fetch job for the dashboard, or None when the card has no job."""
    if job is None:
        return None
    return {
        "job_id": job.id,
        "card_id": job.card_id,
        "status": job.status,
        "error": job.error,
    }


@router.post("/cards/{card_id}/fulltext", status_code=202)
def queue_card_fulltext(request: Request, card_id: int) -> dict:
    """Queue an on-demand fetch + enrich of a card's full text.

    Returns as soon as the job is recorded -- the acquisition ladder runs on the
    background worker, which can take 30-60s on the browser tier. Progress is read back
    via GET on this same path, so it survives the reader pane being destroyed when
    another card is opened.

    Enqueuing a card that already has a job in flight returns that job rather than
    creating a second one, so a double click fetches once.

    Args:
        request: FastAPI request carrying app.state.engine and the fetch worker.
        card_id: Primary key of the card to fetch.

    Returns:
        Dict with {job_id, card_id, status, error}; 404 if the card is unknown.
    """
    engine = request.app.state.engine
    # The unknown-card 404 used to fall out of enrich_item returning None; with the work
    # deferred, the check has to happen here -- before anything is queued.
    with Session(engine) as session:
        if session.get(Card, card_id) is None:
            raise HTTPException(status_code=404, detail="card not found")
    job = enqueue(engine, card_id)
    worker = getattr(request.app.state, "fetch_worker", None)
    if worker is not None:
        worker.wake()
    return _job_payload(job)  # type: ignore[return-value]


@router.get("/fetch-jobs/active")
def list_active_fetch_jobs(request: Request) -> dict:
    """Card ids with a queued or running fetch, for the list's pending markers.

    Deliberately separate from /api/cards so the card-list payload stays
    lean; the dashboard polls this only while at least one job is in flight.
    """
    return {"card_ids": active_card_ids(request.app.state.engine)}
