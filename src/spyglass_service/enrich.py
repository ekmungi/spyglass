# src/spyglass_service/enrich.py
"""Enrichment cascade: relevance-gated fetch -> one combined LLM call -> summary + embed.

No Claude session. Gate 1 (blurb) decides whether to fetch full text; the combined full-text
call confirms relevance AND returns the summary/tags/category. Relevance is persisted so the
daily pass skips already-judged items. The LLM and fetcher are injectable for tests.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.categories import _ensure_category, managed_category_names
from spyglass_service.content_store import store_fulltext
from spyglass_service.documents import fetch_fulltext
from spyglass_service.embeddings import EmbeddingIndex, embed_summary
from spyglass_service.enrich_prompt import (
    ENRICH_SCHEMA,
    EnrichmentResult,
    build_messages,
    bucket_from_score,
    enrich_schema,
    parse_enrichment,
)
from spyglass_service.models import Card, Item, RunLog
from spyglass_service.openrouter import chat_json
from spyglass_service.vault import read_interest_profile

logger = logging.getLogger(__name__)

# Type aliases for injectable dependencies.
LlmFn = Callable[[list[dict]], dict]
FetchFn = Callable[[str], dict]


def _default_llm(settings, categories: list[str] | None = None) -> LlmFn:
    """Bind chat_json to the configured model + key (real network path).

    When a category vocabulary is configured, the schema constrains `category` to that closed
    set; with none configured, the free-text schema is used (unconfigured install).

    Args:
        settings: App settings with enrich_model and openrouter_api_key.
        categories: The managed category names (empty/None -> free-text schema).

    Returns:
        A callable that takes a messages list and returns a parsed JSON dict.
    """
    schema = enrich_schema(categories) if categories else ENRICH_SCHEMA
    return lambda messages: chat_json(
        messages,
        schema,
        model=settings.enrich_model,
        api_key=settings.openrouter_api_key or "",
    )


def _judge(
    llm: LlmFn,
    interest: str,
    title: str,
    body: str,
    *,
    full: bool,
    categories: list[str] | None = None,
    allowed: set[str] | None = None,
) -> EnrichmentResult:
    """One LLM enrichment call; returns a parsed (and clamped) EnrichmentResult.

    Args:
        llm: Injectable LLM callable.
        interest: User interest profile string.
        title: Article title.
        body: Article body (blurb for Gate 1, full markdown for Gate 2).
        full: True when body is the full article text (Gate 2).
        categories: The managed category set, listed for the model (closed vocabulary).
        allowed: The same set for post-validation; a category outside it becomes Unsorted.

    Returns:
        Parsed EnrichmentResult with all fields validated.
    """
    raw = llm(build_messages(interest, title, body, full=full, categories=categories))
    return parse_enrichment(raw, allowed=allowed)


def _apply(session: Session, card: Card, result: EnrichmentResult, *, summarized: bool) -> None:
    """Write a result onto a card: always relevance; summary/tags/category only when summarized.

    Args:
        session: Active SQLModel session (caller must commit).
        card: Card instance to mutate.
        result: Parsed enrichment result from the LLM.
        summarized: Whether to also write summary/tags/category/curated fields.
    """
    card.relevance_score = result.relevance_score
    card.relevance = bucket_from_score(result.relevance_score)
    card.relevance_ai = card.relevance
    card.relevance_reason = result.relevance_reason
    card.relevance_at = datetime.now(UTC)
    if summarized:
        card.summary = result.summary
        card.tags = ",".join(result.tags) if result.tags else None
        if result.fits and result.category:
            _ensure_category(session, result.category)
            card.category = result.category
            card.category_ai = result.category
        card.curated = True
    card.updated_at = datetime.now(UTC)
    session.add(card)


def enrich_item(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    card_id: int,
    *,
    llm: LlmFn | None = None,
    fetcher: FetchFn | None = None,
    bypass_gate: bool = False,
) -> dict | None:
    """Run the full cascade for one card. Returns a small result dict, or None if unknown.

    Cascade:
    - GATE 1 (blurb): Cheap LLM judgment on title + blurb (full=False). If score is below
      settings.relevance_gate, persist the judgment, skip fetch, return recommended=False.
    - FETCH: Fetch the full article. Store the result via store_fulltext regardless of outcome.
    - GATE 2 (full text): If fetch succeeded and returned non-empty markdown, run a combined
      LLM call (full=True) for relevance + summary + tags + category. recommended = score >= gate.
      If fetch failed or returned empty markdown, fall back to Gate-1 judgment, recommended=False.
    - EMBED: On a successful Gate 2, call embed_summary to store the semantic vector.

    Args:
        engine: SQLAlchemy engine.
        index: EmbeddingIndex for storing the summary vector.
        settings: App settings (relevance_gate, enrich_model, openrouter_api_key).
        card_id: Primary key of the Card to process.
        llm: Optional injectable LLM callable (for tests; defaults to real OpenRouter call).
        fetcher: Optional injectable fetch callable (for tests; defaults to fetch_fulltext).
        bypass_gate: When True, skip the Gate-1 relevance cutoff and always fetch the full text.
            Set for an explicit user 'fetch full text' action, which must never be throttled by
            the gate (the gate only cost-controls the automatic daily pass).

    Returns:
        Dict with {relevance_score, recommended, summary, category}, or None if card not found.
    """
    # The managed category vocabulary: the LLM is constrained to this closed set, and
    # `allowed` is the post-validation backstop. Empty (unconfigured) -> free-text, unconstrained.
    categories = managed_category_names(engine)
    allowed = set(categories) or None
    llm = llm or _default_llm(settings, categories)
    interest = read_interest_profile(settings)
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, card.item_id) if card else None
        if card is None or item is None:
            return None
        title, url, blurb = item.title, item.url, (item.summary or "")

    # GATE 1 -- only for the automatic daily pass. A manual fetch (bypass_gate) skips it
    # entirely: the user wants the text, so we don't spend an LLM call judging relevance before
    # fetching. Gate-2 on the full text is the sole LLM call on the manual path.
    if not bypass_gate:
        g1 = _judge(llm, interest, title, blurb, full=False, categories=categories, allowed=allowed)
        if g1.relevance_score < settings.relevance_gate:
            with Session(engine) as session:
                _apply(session, session.get(Card, card_id), g1, summarized=False)
                session.commit()
            return {"relevance_score": g1.relevance_score, "recommended": False, "summary": "", "category": None}
    else:
        g1 = None  # no Gate-1 judgment on the manual path

    # FETCH (gated -- only executed when Gate 1 passes, or always when bypass_gate is set).
    # A test-injected fetcher is called url-only (the seam tests pin this shape); the real
    # production path (fetcher is None) threads settings+engine through so the Settings-built
    # ladder (Jina/browser toggles) and the per-domain method cache actually
    # activate on BOTH triggers -- the automatic pass (enrich_pending) and the manual
    # 'fetch full text' button (bypass_gate, via the fetch queue's default runner) -- since
    # both call through this same enrich_item. Calling fetch_fulltext(url) bare would run the
    # curl-only fallback ladder with no per-domain cache.
    if fetcher is not None:
        fetched = fetcher(url)
    else:
        fetched = fetch_fulltext(url, settings=settings, engine=engine)
    store_fulltext(
        engine,
        item_id=item.id,
        markdown=fetched["markdown"],
        source_url=fetched.get("source_url"),
        content_type=fetched.get("content_type"),
        status=fetched["status"],
        error=fetched.get("error"),
        # Structured, card-visible failure record --
        # populated by documents.fetch_fulltext on both success and failure;
        # .get() so a fetcher/lane without the structured keys still
        # stores cleanly, defaulting all four to None.
        detected_type=fetched.get("detected_type"),
        tier_reached=fetched.get("tier_reached"),
        http_status=fetched.get("http_status"),
        error_class=fetched.get("error_class"),
    )
    if fetched["status"] != "ok" or not fetched["markdown"].strip():
        # No usable full text. On the automatic path, fall back to the Gate-1 (blurb) judgment.
        # On the manual path there is no g1 -- the fetch was explicitly requested, so surface the
        # failure via the stored status (the reader renders `failed`) without inventing a relevance.
        if g1 is not None:
            with Session(engine) as session:
                _apply(session, session.get(Card, card_id), g1, summarized=False)
                session.commit()
        return {"relevance_score": g1.relevance_score if g1 else None,
                "recommended": False, "summary": "", "category": None}

    # GATE 2 (combined) -- relevance + summary on full text. Non-fatal on the manual path: the
    # text is already stored, so an LLM failure must not lose it or 500 the on-demand request.
    # The vector is a backfillable extra (its own try/except below).
    try:
        g2 = _judge(
            llm, interest, title, fetched["markdown"], full=True,
            categories=categories, allowed=allowed,
        )
    except Exception:  # noqa: BLE001 -- never lose stored text to an LLM failure
        logger.exception("Gate-2 LLM call failed for card %s; text stored, summary skipped", card_id)
        return {"relevance_score": None, "recommended": False, "summary": "", "category": None}
    recommended = g2.relevance_score >= settings.relevance_gate
    with Session(engine) as session:
        _apply(session, session.get(Card, card_id), g2, summarized=True)
        session.commit()
    # The summary is the valuable output and is already committed; a failed embed (e.g. a
    # missing model file) must not lose it or 500 the on-demand request. The vector is a
    # backfillable extra -- the background shallow-embed pass re-covers items lacking one.
    try:
        embed_summary(engine, index, item.id, title, g2.summary, g2.tags)
    except Exception:  # noqa: BLE001 -- never let embedding failure abort a successful enrichment
        logger.exception("embed_summary failed for item %s; summary saved, embedding skipped", item.id)
    return {"relevance_score": g2.relevance_score, "recommended": recommended,
            "summary": g2.summary, "category": g2.category}


def enrich_pending(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    *,
    llm: LlmFn | None = None,
    fetcher: FetchFn | None = None,
    limit: int | None = None,
) -> dict:
    """Daily pass: enrich every not-yet-judged card (Card.relevance_at IS NULL).

    Per-item try/except so one failure never aborts the batch. Skips already-judged cards
    (relevance caching -- avoids re-running expensive LLM calls on cards that have already
    been scored).

    Args:
        engine: SQLAlchemy engine.
        index: EmbeddingIndex for storing summary vectors.
        settings: App settings.
        llm: Optional injectable LLM callable (for tests).
        fetcher: Optional injectable fetch callable (for tests).
        limit: Optional cap on how many cards to process in one pass.

    Returns:
        Tally dict with keys: judged, fetched, recommended, dropped.
    """
    with Session(engine) as session:
        statement = select(Card.id).where(Card.relevance_at.is_(None))  # type: ignore[union-attr]
        if limit:
            statement = statement.limit(limit)
        card_ids = list(session.exec(statement).all())
    tally = {"judged": 0, "fetched": 0, "recommended": 0, "dropped": 0}
    for cid in card_ids:
        try:
            out = enrich_item(engine, index, settings, cid, llm=llm, fetcher=fetcher)
        except Exception:  # noqa: BLE001 -- one bad item must not abort the daily pass
            logger.exception("enrich failed for card %s", cid)
            continue
        if out is None:
            continue
        tally["judged"] += 1
        if out["summary"]:
            tally["fetched"] += 1
        tally["recommended" if out["recommended"] else "dropped"] += 1
    return tally


def run_scheduled_enrich(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    *,
    force: bool = False,
    max_age: timedelta = timedelta(hours=24),
    llm: LlmFn | None = None,
    fetcher: FetchFn | None = None,
) -> dict | None:
    """Run the enrichment pass, guarded to at most once per ``max_age`` unless ``force``.

    The startup daily sweep passes ``force=False`` (the guard throttles it); the refresh
    path passes ``force=True`` when new items arrived, so freshly-collected cards are judged
    promptly instead of waiting for the next restart. ``enrich_pending`` self-limits
    to unjudged cards (``relevance_at IS NULL``), so a forced run only costs LLM calls for
    genuinely-pending items. Logs one ``RunLog(source="enrich")``. Returns the tally, or
    ``None`` when the guard skips the run.
    """
    from spyglass_service.refresh import enrich_is_stale  # local import avoids an import cycle

    if not force and not enrich_is_stale(engine, max_age):
        return None
    run = RunLog(source="enrich", status="running")
    tally: dict | None = None
    try:
        tally = enrich_pending(engine, index, settings, llm=llm, fetcher=fetcher)
        run.status, run.detail = "ok", str(tally)
    except Exception as exc:  # noqa: BLE001 -- never crash the caller (startup or a refresh)
        run.status, run.detail = "error", str(exc)
    run.finished_at = datetime.now(UTC)
    with Session(engine) as session:
        session.add(run)
        session.commit()
    return tally
