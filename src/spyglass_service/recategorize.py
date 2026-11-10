"""Recategorize pass: a mechanical, embedding-only maintenance job.

Two steps over the arctic vectors, no per-item LLM:
  1. Re-assign each Unsorted, non-overridden card to the nearest existing category centroid when
     it clearly belongs (cheap nearest-centroid).
  2. Cluster whatever stays Unsorted into candidate NEW categories (name + size + members). The
     user accepts or discards each in Settings; a new category enters the set only on accept.

Non-destructive: cards with a user category override are never touched. Each run is
recorded as a RunLog(source="recategorize") whose detail is the JSON the Settings UI polls.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.categories import (
    CategoryResult,
    add_category,
    apply_categories,
    managed_category_names,
)
from spyglass_service.classify import Classifier, default_classifier
from spyglass_service.cluster import cluster_cosine
from spyglass_service.cluster_name import default_namer
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Card, CardState, Item, RunLog

logger = logging.getLogger(__name__)

RECATEGORIZE_SOURCE = "recategorize"
# Re-assignment is an LLM enum re-classify over each Unsorted card's stored summary, constrained to
# the user's categories (+ null). Calibration proved embeddings cannot map to these intent-based
# categories (they cut across topical similarity), so only the LLM -- which reads application --
# can file the backlog onto the user's chosen taxonomy (classify.py).
#
# Clustering still discovers candidate sub-topics in the Unsorted residual. arctic-embed-s packs
# this all-AI corpus into a tight cone (nearest-neighbour cosine ~0.8), so the cluster threshold is
# high: 0.80 surfaced ~11 coherent groups on the real corpus; lower values merge everything.
CLUSTER_THRESHOLD = 0.80
MIN_CLUSTER_SIZE = 8
# Example titles carried on each candidate for the review UI; and how many titles feed the namer.
CANDIDATE_EXAMPLES = 4
NAME_SAMPLE = 12
# The re-classify pass makes one LLM call per Unsorted card, so a full backlog run can take many
# minutes. A 'running' row older than this is treated as abandoned (crashed/killed mid-run) so a new
# kick can proceed rather than deadlocking forever on a zombie row (adversarial review #1).
RECATEGORIZE_STALE_AFTER = timedelta(hours=2)

Namer = Callable[[list[str]], str]


def _unsorted_rows(session: Session) -> list[tuple[int, int, str]]:
    """(card_id, item_id, title) for every Unsorted, non-overridden, non-dismissed card.

    The single definition of the Recategorize working set: overridden cards are excluded so a
    user's hand placement is never disturbed; dismissed cards are archived, out of scope.
    """
    return list(
        session.exec(
            select(Card.id, Card.item_id, Item.title)
            .where(Card.item_id == Item.id)
            .where(Card.category.is_(None))  # type: ignore[union-attr]
            .where(Card.category_override.is_(False))  # type: ignore[union-attr]
            .where(Card.state != CardState.DISMISSED)
        ).all()
    )


def _aligned_vectors(
    rows: list[tuple[int, int, str]], index: EmbeddingIndex
) -> tuple[list[int], list[str], np.ndarray]:
    """Working-set rows aligned 1:1 with their index vectors, race-safe.

    Takes the alignment from ``matrix_for``'s returned ``found_ids`` -- a single atomic index
    snapshot -- rather than a separate ``index.has()`` check, so a concurrent index mutation can
    neither crash the pass on a length mismatch nor silently shift a vector onto the wrong card
    (adversarial review #2). ``found_ids`` is an order-preserving subsequence of the requested
    item ids (duplicates included), so a two-pointer walk recovers each present row's card id.

    Args:
        rows: (card_id, item_id, title) working-set rows, in a stable order.
        index: The in-memory embedding index.

    Returns:
        (card_ids, titles, matrix) where matrix[i] is the vector for card_ids[i]; cards whose
        item vector is absent from the index are skipped. matrix has one row per returned card id.
    """
    found_ids, matrix = index.matrix_for([iid for _cid, iid, _title in rows])
    card_ids: list[int] = []
    titles: list[str] = []
    ptr = 0
    for cid, iid, title in rows:
        if ptr < len(found_ids) and found_ids[ptr] == iid:
            card_ids.append(cid)
            titles.append(title)
            ptr += 1
    return card_ids, titles, matrix


def _unsorted_rows_full(session: Session) -> list[tuple[int, str, str, str | None]]:
    """(card_id, title, summary, tags) for every Unsorted, non-overridden, non-dismissed card.

    The re-classify working set. Overridden cards are excluded so a hand placement is never
    disturbed; dismissed cards are archived and out of scope.
    """
    return list(
        session.exec(
            select(Card.id, Item.title, Card.summary, Card.tags)
            .where(Card.item_id == Item.id)
            .where(Card.category.is_(None))  # type: ignore[union-attr]
            .where(Card.category_override.is_(False))  # type: ignore[union-attr]
            .where(Card.state != CardState.DISMISSED)
        ).all()
    )


def reclassify_unsorted(engine: Engine, settings, *, classifier: Classifier | None = None) -> int:
    """File each Unsorted card into one of the user's categories via the enum LLM classifier.

    One LLM call per Unsorted, non-overridden card over its STORED summary (no re-fetch),
    constrained to the managed set (+ null = leave Unsorted). Per-item try/except so one failure
    never aborts the batch. Applied through ``apply_categories``, which re-baselines category_ai and
    skips any overridden card. No categories configured -> no-op.

    Args:
        engine: The service database engine.
        settings: App settings (enrich_model, openrouter_api_key) for the default classifier.
        classifier: Injectable classifier for tests; defaults to the real OpenRouter enum call.

    Returns:
        How many cards were filed into a category.
    """
    categories = managed_category_names(engine)
    if not categories:
        return 0
    classifier = classifier or default_classifier(settings, categories)
    with Session(engine) as session:
        rows = _unsorted_rows_full(session)
    results: list[CategoryResult] = []
    for card_id, title, summary, tags in rows:
        tag_list = tags.split(",") if tags else []
        try:
            category = classifier(title, summary or "", tag_list)
        except Exception:  # noqa: BLE001 -- one bad item must not abort the whole re-classify
            logger.exception("classify failed for card %s", card_id)
            continue
        if category is not None:
            results.append(CategoryResult(card_id=card_id, category=category))
    return apply_categories(engine, results) if results else 0


def build_candidates(
    engine: Engine,
    index: EmbeddingIndex,
    *,
    threshold: float = CLUSTER_THRESHOLD,
    min_size: int = MIN_CLUSTER_SIZE,
    namer: Namer,
) -> list[dict]:
    """Cluster the still-Unsorted pile into candidate new categories.

    Each dense cluster (only when the embeddings genuinely cluster) becomes one
    candidate ``{suggested_name, size, card_ids, examples}``. The name comes from one cheap LLM
    call over a sample of the cluster's titles.

    Returns:
        The candidate list (empty when nothing reaches ``min_size``), largest cluster first.
    """
    with Session(engine) as session:
        rows = _unsorted_rows(session)
    card_ids, all_titles, matrix = _aligned_vectors(rows, index)
    if len(card_ids) < min_size:
        return []
    clusters = cluster_cosine(matrix, threshold=threshold, min_size=min_size)
    candidates: list[dict] = []
    for cluster in clusters:
        member_card_ids = [card_ids[i] for i in cluster]
        titles = [all_titles[i] for i in cluster]
        suggested = namer(titles[:NAME_SAMPLE]) or "New Category"
        candidates.append(
            {
                "suggested_name": suggested,
                "size": len(cluster),
                "card_ids": member_card_ids,
                "examples": titles[:CANDIDATE_EXAMPLES],
            }
        )
    return candidates


def run_recategorize(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    *,
    namer: Namer | None = None,
    classifier: Classifier | None = None,
    cluster_threshold: float = CLUSTER_THRESHOLD,
    min_size: int = MIN_CLUSTER_SIZE,
) -> dict:
    """Run the full pass: re-assign, then cluster the remainder into candidates.

    Records a RunLog(source="recategorize") -- 'running' while it works, then 'ok' with the JSON
    result (or 'error'). Never raises: a failure is logged and captured so the background job and
    its caller stay alive (mirrors run_scheduled_enrich).

    Returns:
        ``{"assigned": n, "candidates": [...]}`` (or ``{"assigned": 0, "candidates": [], "error"}``).
    """
    namer = namer or default_namer(settings)
    with Session(engine) as session:
        run = RunLog(source=RECATEGORIZE_SOURCE, status="running")
        session.add(run)
        session.commit()
        run_id = run.id
    # Reassignment commits first, so its count is reported even if the later cluster/naming step
    # fails -- the pass is non-fatal and a failure never rolls back valid assignments.
    assigned = 0
    try:
        assigned = reclassify_unsorted(engine, settings, classifier=classifier)
        candidates = build_candidates(
            engine, index, threshold=cluster_threshold, min_size=min_size, namer=namer
        )
        result = {"assigned": assigned, "candidates": candidates}
        status, detail = "ok", json.dumps(result)
    except Exception as exc:  # noqa: BLE001 -- never crash the background job or its caller
        logger.exception("recategorize failed")
        result = {"assigned": assigned, "candidates": [], "error": str(exc)}
        status, detail = "error", json.dumps({"assigned": assigned, "error": str(exc)})
    with Session(engine) as session:
        row = session.get(RunLog, run_id)
        # Defensive: the row could be gone (DB reset/restore mid-run). Guarding it here keeps the
        # finalize from raising out of the background task (adversarial review #1).
        if row is not None:
            row.status, row.detail, row.finished_at = status, detail, datetime.now(UTC)
            session.add(row)
            session.commit()
    return result


def _latest_run(session: Session) -> RunLog | None:
    """The most recent recategorize RunLog row, or None if the pass has never run."""
    return session.exec(
        select(RunLog)
        .where(RunLog.source == RECATEGORIZE_SOURCE)
        .order_by(RunLog.started_at.desc())  # type: ignore[attr-defined]
    ).first()


def latest_candidates(engine: Engine) -> dict:
    """The last run's status + candidates for the Settings review UI.

    Returns:
        ``{"status": "none", "candidates": []}`` before any run; otherwise the run's status
        ("running" | "ok" | "error"), assigned count, and candidate list parsed from its detail.
    """
    with Session(engine) as session:
        row = _latest_run(session)
    if row is None:
        return {"status": "none", "candidates": []}
    try:
        data = json.loads(row.detail) if row.detail else {}
    except (ValueError, TypeError):
        data = {}
    return {
        "status": row.status,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "assigned": data.get("assigned", 0),
        "candidates": data.get("candidates", []),
    }


def is_recategorize_running(engine: Engine) -> bool:
    """True when a recategorize job is genuinely in flight.

    A 'running' row with no finish time reads as running -- unless it is older than
    RECATEGORIZE_STALE_AFTER, in which case it is an abandoned run (the process died mid-pass) and
    a new kick is allowed to proceed. Without this age check one crash would deadlock every future
    kick forever (adversarial review #1).
    """
    with Session(engine) as session:
        row = _latest_run(session)
    if not row or row.status != "running" or row.finished_at is not None:
        return False
    started = row.started_at
    if started.tzinfo is None:  # stored timestamps may be naive; treat as UTC (matches is_stale)
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) - started <= RECATEGORIZE_STALE_AFTER


def accept_candidate(engine: Engine, name: str, card_ids: list[int]) -> dict:
    """Accept a discovered cluster: register the category and file its cards into it.

    The new category enters the managed set here (the only non-manual way it can).
    Assignment goes through ``apply_categories`` so an overridden card among the members is
    still respected.

    Returns:
        ``{"name": name, "assigned": n}``.
    """
    add_category(engine, name)
    results = [CategoryResult(card_id=cid, category=name) for cid in card_ids]
    assigned = apply_categories(engine, results) if results else 0
    return {"name": name, "assigned": assigned}
