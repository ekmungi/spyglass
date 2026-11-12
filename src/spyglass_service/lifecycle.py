"""Card lifecycle teardown: archive / unarchive + the source-aware Raindrop cascade.

Archiving sets a card to DISMISSED -- the existing "archived, never deleted" state
(hidden from the default list, restorable from the Archive tab). The optional Raindrop
cascade moves the underlying bookmark to a "Processed" collection for Raindrop-sourced
items ONLY; RSS/arXiv items have no bookmark, so the cascade branches on Item.source.

delete_cards performs a full local hard-delete: highlights -> content/fts ->
card -> item, then writes a tombstone so the item is never re-collected. For Raindrop
items the underlying bookmark is also moved to the Processed collection (non-destructive).
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.raindrop import (
    RaindropError,
    move_bookmark_to_collection,
    resolve_processed_collection,
)
from spyglass_service.config import Settings
from spyglass_service.content_store import delete_content
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.highlights import delete_for_card
from spyglass_service.models import Card, CardState, Embedding, InboxEntry, Item, Tombstone
from spyglass_service.radar import from_you_store


def add_tombstone(engine: Engine, source: str, external_id: str) -> None:
    """Record a deletion gravestone so re-collection skips this (source, external_id).

    Idempotent: a second call for the same pair is a no-op (not an error).
    """
    with Session(engine) as session:
        existing = session.exec(
            select(Tombstone).where(
                Tombstone.source == source,
                Tombstone.external_id == external_id,
            )
        ).first()
        if existing is not None:
            return
        session.add(Tombstone(source=source, external_id=external_id))
        session.commit()


def _set_state(
    engine: Engine,
    card_ids: list[int],
    new_state: CardState,
    only_from: CardState | None = None,
) -> int:
    """Flip the given cards to new_state, skipping unknown ids. When only_from is set,
    a card is changed only if it is currently in that state. Returns how many changed."""
    changed = 0
    with Session(engine) as session:
        for card_id in card_ids:
            card = session.get(Card, card_id)
            if card is None:
                continue
            if only_from is not None and card.state != only_from:
                continue
            card.state = new_state
            card.updated_at = datetime.now(UTC)
            session.add(card)
            changed += 1
        session.commit()
    return changed


def archive_cards(engine: Engine, card_ids: list[int]) -> int:
    """Soft-archive cards: set them to DISMISSED (hidden from the default list,
    restorable, never deleted). Unknown ids are skipped. Returns how many were archived."""
    return _set_state(engine, card_ids, CardState.DISMISSED)


def unarchive_cards(engine: Engine, card_ids: list[int]) -> int:
    """Restore archived (DISMISSED) cards to NEW so they reappear in the default list.
    Only cards currently dismissed are flipped; other states are left untouched.
    Returns how many were restored."""
    return _set_state(engine, card_ids, CardState.NEW, only_from=CardState.DISMISSED)


def delete_cards(
    engine: Engine,
    settings: Settings,
    card_ids: list[int],
    client: httpx.Client | None = None,
    index: EmbeddingIndex | None = None,
) -> dict:
    """Hard-delete a set of cards and all their dependent rows, then tombstone each item.

    For each card id (unknown ids are silently skipped):
      1. Resolve (item_id, source, external_id) while the rows are still live.
      2. Delete all Highlights for the card (FK-safe: highlights reference card).
      3. Delete the stored Content/FTS for the item.
      4. Delete the Embedding row and evict the vector from index (when provided).
      5. Delete the Card row, then the Item row.
      6. Write a Tombstone so re-collection is permanently blocked.

    For Raindrop-sourced cards, additionally moves the underlying bookmark to the
    "Processed" collection (non-destructive, reversible in Raindrop). The raindrop_token
    must be configured; if absent, the local delete still proceeds and result["raindrop"]
    carries {"error": "..."}. RSS/arXiv-only batches leave result["raindrop"] == {}.

    index: when provided, calls index.remove(item_id) after deleting the Embedding row so
    the in-memory matrix stays consistent with the DB. Safe no-op if the id is absent.

    Returns {"deleted": <n>, "raindrop": <cascade_result>}.
    """
    # Resolve card -> item data before any deletes so we never touch detached rows.
    targets: list[tuple[int, int, str, str]] = []
    with Session(engine) as session:
        for card_id in card_ids:
            card = session.get(Card, card_id)
            if card is None:
                continue
            item = session.get(Item, card.item_id)
            if item is None:
                continue
            targets.append((card_id, item.id, item.source, item.external_id))

    # Capture raindrop pairs BEFORE local teardown while source/external_id are known.
    raindrop_pairs: list[tuple[int, str]] = [
        (card_id, external_id)
        for card_id, _item_id, source, external_id in targets
        if source == "raindrop"
    ]

    deleted = 0
    for card_id, item_id, source, external_id in targets:
        # Tombstone first: if any subsequent delete fails the item is still permanently
        # blocked from re-collection. source/external_id were resolved above while the
        # rows were live, so this is safe to call before the deletes.
        add_tombstone(engine, source, external_id)
        # FK-safe order: highlights -> content/fts -> embedding -> card -> item
        delete_for_card(engine, card_id)
        delete_content(engine, item_id)
        with Session(engine) as session:
            embedding = session.exec(select(Embedding).where(Embedding.item_id == item_id)).first()
            if embedding is not None:
                session.delete(embedding)
                session.commit()
        if index is not None:
            index.remove(item_id)
        with Session(engine) as session:
            for entry in session.exec(select(InboxEntry).where(InboxEntry.card_id == card_id)):
                session.delete(entry)
            card = session.get(Card, card_id)
            if card is not None:
                session.delete(card)
            session.commit()
        with Session(engine) as session:
            item = session.get(Item, item_id)
            if item is not None:
                session.delete(item)
                session.commit()
        # A picture or PDF the reader sent in is kept in its own store until its item is deleted.
        from_you_store.remove(settings.data_dir, item_id)
        deleted += 1

    # No Raindrop items in this batch -- nothing to cascade.
    if not raindrop_pairs:
        return {"deleted": deleted, "raindrop": {}}

    token = settings.raindrop_token
    if not token:
        return {
            "deleted": deleted,
            "raindrop": {"error": "raindrop_token is not configured"},
        }

    # Resolve the Processed collection once; move each bookmark into it.
    try:
        collection_id = resolve_processed_collection(token, client=client)
    except RaindropError as exc:
        errors = [{"card_id": cid, "error": str(exc)} for cid, _ in raindrop_pairs]
        return {"deleted": deleted, "raindrop": {"moved": 0, "errors": errors}}

    moved = 0
    errors: list[dict] = []
    for card_id, external_id in raindrop_pairs:
        try:
            move_bookmark_to_collection(token, external_id, collection_id, client=client)
            moved += 1
        except RaindropError as exc:
            errors.append({"card_id": card_id, "error": str(exc)})

    return {"deleted": deleted, "raindrop": {"moved": moved, "errors": errors}}


def cascade_raindrop_removal(
    engine: Engine,
    settings: Settings,
    card_ids: list[int],
    client: httpx.Client | None = None,
) -> dict:
    """Move each Raindrop-sourced card's bookmark to the 'Processed' collection.

    The bookmark id is Item.external_id. RSS/arXiv items carry no bookmark and are
    skipped (source-aware). The Processed collection is resolved once; per-item move
    failures are captured, never raised, so one bad id cannot abort the batch.
    Returns {removed, skipped_non_raindrop, errors:[{card_id, error}]}; "removed" means
    "moved to Processed". With no token configured, returns {..., error} and moves nothing.
    """
    token = settings.raindrop_token
    if not token:
        return {
            "removed": 0,
            "skipped_non_raindrop": 0,
            "errors": [],
            "error": "raindrop_token is not configured",
        }

    # Resolve (card_id, source, external_id) inside the session so the HTTP calls
    # below never touch detached ORM instances.
    targets: list[tuple[int, str | None, str | None]] = []
    with Session(engine) as session:
        for card_id in card_ids:
            card = session.get(Card, card_id)
            item = session.get(Item, card.item_id) if card else None
            if item is None:
                targets.append((card_id, None, None))
            else:
                targets.append((card_id, item.source, item.external_id))

    # Separate not-found errors, non-raindrop skips, and raindrop targets upfront.
    errors: list[dict] = [
        {"card_id": cid, "error": "card not found"}
        for cid, src, _ in targets
        if src is None
    ]
    skipped = sum(1 for _, src, _ in targets if src is not None and src != "raindrop")
    raindrop_targets = [
        (cid, ext_id)
        for cid, src, ext_id in targets
        if src == "raindrop"
    ]

    if not raindrop_targets:
        return {"removed": 0, "skipped_non_raindrop": skipped, "errors": errors}

    # Resolve the Processed collection once before iterating over items.
    try:
        collection_id = resolve_processed_collection(token, client=client)
    except RaindropError as exc:
        errors.extend({"card_id": cid, "error": str(exc)} for cid, _ in raindrop_targets)
        return {"removed": 0, "skipped_non_raindrop": skipped, "errors": errors}

    removed = 0
    for card_id, external_id in raindrop_targets:
        try:
            move_bookmark_to_collection(token, external_id, collection_id, client=client)
            removed += 1
        except RaindropError as exc:
            errors.append({"card_id": card_id, "error": str(exc)})

    return {"removed": removed, "skipped_non_raindrop": skipped, "errors": errors}
