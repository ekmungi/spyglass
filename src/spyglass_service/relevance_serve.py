"""DB/index adapter for the semantic-propagation relevance model.

Gathers the user's thumb labels + their embedding vectors and computes each card's blended
effective relevance via the pure ``relevance_model`` core. Kept in its own module so
``relevance_model`` stays a pure, matrix-only unit with no DB or index coupling.
"""

from datetime import UTC, datetime

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Card, Item
from spyglass_service.relevance_model import (
    Label,
    effective_level,
    knn_term,
    score_of_level,
)


def build_label_pool(engine: Engine) -> list[Label]:
    """All thumbed cards as propagation labels: up = +1, down = -1, with age in days.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        One Label per card with a thumb, keyed by the card's item_id (the embedding key).
    """
    now = datetime.now(UTC)
    with Session(engine) as session:
        cards = session.exec(
            select(Card).where(Card.feedback.in_(("up", "down")))  # type: ignore[union-attr]
        ).all()
    # Dedupe by item_id, keeping the most recent thumb: Card.item_id is not unique, so two
    # cards could point at the same article. Collapsing here gives one label per item (a clean
    # contract for the k-NN matmul) and prevents a single article from voting twice.
    by_item: dict[int, Label] = {}
    for card in cards:
        polarity = 1.0 if card.feedback == "up" else -1.0
        if card.feedback_at is not None:
            at = card.feedback_at
            # Stored timestamps may be naive; treat them as UTC for the age arithmetic.
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            age_days = max(0.0, (now - at).total_seconds() / 86400.0)
        else:
            age_days = 0.0
        existing = by_item.get(card.item_id)
        # Smaller age_days == more recent; the freshest thumb on an item wins.
        if existing is None or age_days < existing.age_days:
            by_item[card.item_id] = Label(item_id=card.item_id, polarity=polarity, age_days=age_days)
    return list(by_item.values())


def effective_relevance_map(
    engine: Engine, index: EmbeddingIndex, rows: list[tuple[Card, Item]]
) -> dict[int, str | None]:
    """Compute each card's displayed relevance level (or None) for the given rows.

    Explicit labels (override / thumb-down OUT pin) win on their own item; a card never scored
    and never thumbed is unjudged (None); everything else blends its LLM prior with a semantic
    k-NN vote from the thumb labels. Propagation is over embedding cosine ONLY.

    Args:
        engine: SQLAlchemy engine (used to load the thumb label pool).
        index: The in-memory embedding index (for label + query vectors).
        rows: The (Card, Item) rows being served, as list_cards fetched them.

    Returns:
        Mapping of card.id -> effective relevance level, or None for an unjudged card.
    """
    pool = build_label_pool(engine)
    found_ids, label_matrix = index.matrix_for([label.item_id for label in pool])
    pol_by_id = {label.item_id: label.polarity for label in pool}
    age_by_id = {label.item_id: label.age_days for label in pool}
    polarities = np.array([pol_by_id[i] for i in found_ids], dtype=np.float64)
    ages = np.array([age_by_id[i] for i in found_ids], dtype=np.float64)

    # One batched matmul for every query card that has a vector: cosine == dot on normalized rows.
    query_found, query_matrix = index.matrix_for([item.id for _card, item in rows])
    if found_ids and query_found:
        sims = query_matrix @ label_matrix.T  # (n_query, n_labels)
        sims_by_item = {iid: sims[i] for i, iid in enumerate(query_found)}
    else:
        sims_by_item = {}

    out: dict[int, str | None] = {}
    for card, item in rows:
        override_level = card.relevance if card.relevance_override else None
        truly_unjudged = (
            card.relevance_at is None and card.feedback is None and not card.relevance_override
        )
        prior = (
            float(card.relevance_score)
            if card.relevance_score is not None
            else score_of_level(card.relevance)
        )
        sims_row = sims_by_item.get(item.id)
        knn = knn_term(sims_row, polarities, ages) if sims_row is not None else 0.0
        out[card.id] = effective_level(
            override_level=override_level,
            truly_unjudged=truly_unjudged,
            prior_score=prior,
            knn=knn,
        )
    return out
