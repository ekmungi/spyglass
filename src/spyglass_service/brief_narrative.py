# src/spyglass_service/brief_narrative.py
"""Daily Brief narrative + assembly internals: LLM payload -> brief markdown.

Shared by compose_due_briefs (new briefs) and recompose_brief (rebuilding an existing one):
run the structured-narrative LLM call over the featured items, validate the
{lead, sections} payload strictly (anything malformed pauses -- nothing is written),
and assemble the final markdown deterministically (links, References, Also noticed).
"""

import logging
from collections.abc import Callable

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.brief_prompt import BRIEF_SCHEMA, build_brief_messages, item_block
from spyglass_service.brief_render import Bullet, FeaturedEntry, render_brief_markdown
from spyglass_service.brief_render import _REF_TOKEN
from spyglass_service.brief_time import local_day
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Card, CardState, Item
from spyglass_service.openrouter import chat_json
from spyglass_service.relevance_serve import effective_relevance_map
from spyglass_service.source_label import display_origin, user_feed_names
from spyglass_service.vault import read_interest_profile

logger = logging.getLogger(__name__)

# Injectable LLM callable: messages in, parsed JSON dict out (same shape as enrich.LlmFn).
LlmFn = Callable[[list[dict]], dict]

# References "(related:)" backlinks: min cosine + count, among PREVIOUSLY-BRIEFED cards.
_RELATED_MIN_COS = 0.5
_RELATED_K = 2
# Inline per-bullet related items: nearest OTHER corpus cards to a bullet's
# articles, excluding cards already in this brief. Tighter threshold than the backlinks
# so the "Related:" sub-line only surfaces genuinely-close work; capped small to stay quiet.
_INLINE_RELATED_MIN_COS = 0.55
_INLINE_RELATED_K = 3
# Deterministic lead when nothing cleared the featured bar but low items exist:
# the listed-only brief renders this fixed line with zero thematic sections.
NO_FEATURED_LEAD = "Nothing crossed the relevance bar for a full write-up in this window."


class BriefComposeError(RuntimeError):
    """Raised when the brief narrative cannot be obtained (LLM failure). Nothing is written."""


def _default_llm(settings) -> LlmFn:
    """Bind chat_json to the configured model + key for the brief narrative call.

    Args:
        settings: App settings with enrich_model and openrouter_api_key.

    Returns:
        A callable taking a messages list and returning the parsed {lead, sections} dict.
    """
    return lambda messages: chat_json(
        messages,
        BRIEF_SCHEMA,
        model=settings.enrich_model,
        api_key=settings.openrouter_api_key or "",
    )


def parse_brief_payload(payload: dict) -> tuple[str, list[tuple[str, list[str]]]]:
    """Validate the LLM's {lead, sections:[{heading, bullets}]} payload; malformed means pause.

    A malformed payload is an LLM failure like any other: pausing beats persisting a
    brief with a heading-less blob or an empty bullet (the grouped-bullet
    contract).

    Args:
        payload: The parsed JSON dict the LLM returned.

    Returns:
        (lead, [(heading, [bullet, ...]), ...]) with heading whitespace-trimmed.

    Raises:
        BriefComposeError: lead missing/blank; sections missing/empty/not a list; or any
            section lacking a non-blank string heading or a non-empty list of non-blank
            string bullets.
    """
    lead = payload.get("lead") if isinstance(payload, dict) else None
    if not isinstance(lead, str) or not lead.strip():
        logger.error("brief lead malformed (%r); brief not composed", type(lead))
        raise BriefComposeError("LLM returned no usable lead")
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        logger.error("brief sections malformed (%r); brief not composed", type(raw_sections))
        raise BriefComposeError("LLM returned no usable sections")
    sections: list[tuple[str, list[str]]] = []
    for raw in raw_sections:
        heading = raw.get("heading") if isinstance(raw, dict) else None
        bullets = raw.get("bullets") if isinstance(raw, dict) else None
        if not isinstance(heading, str) or not heading.strip():
            logger.error("brief section heading malformed (%r); brief not composed", raw)
            raise BriefComposeError("LLM returned a malformed section heading")
        if not isinstance(bullets, list) or not bullets or not all(
            isinstance(b, str) and b.strip() for b in bullets
        ):
            logger.error("brief section bullets malformed (%r); brief not composed", raw)
            raise BriefComposeError("LLM returned malformed section bullets")
        sections.append((heading.strip(), bullets))
    return lead, sections


def _related_for(
    session: Session, index: EmbeddingIndex, item_id: int
) -> list[tuple[str, int]]:
    """Top related previously-briefed cards for one featured item, by embedding cosine.

    Only cards already stamped with a brief_id qualify -- a past brief, or a brief composed
    earlier in the same catch-up run (publish-day windowing composes newest-day-first, so an
    older digest may point forward to a card in a newer same-run brief). The reader can still
    jump to that context; at most _RELATED_K neighbours at cosine >= _RELATED_MIN_COS.

    Args:
        session: Active session (read-only use).
        index: In-memory embedding index (item_id keyed).
        item_id: The featured item to find neighbours for.

    Returns:
        Up to two (title, card_id) tuples, best match first.
    """
    out: list[tuple[str, int]] = []
    # A featured card can predate its embedding (the embed pass runs separately); no
    # vector simply means no related links, never a crash after the LLM spend.
    if not index.has(item_id):
        return out
    # k is generous because similar() ranks over ALL items; most neighbours won't be briefed.
    for neighbour_id, score in index.similar(item_id, k=25):
        if score < _RELATED_MIN_COS:
            break  # results are sorted, nothing further can qualify
        row = session.exec(
            select(Card, Item)
            .where(Card.item_id == Item.id)
            .where(Item.id == neighbour_id)
            .where(Card.brief_id != None)  # noqa: E711 -- briefed cards only
        ).first()
        if row is not None:
            out.append((row[1].title, row[0].id))
            if len(out) >= _RELATED_K:
                break
    return out


def _inline_related_for_bullet(
    engine: Engine,
    session: Session,
    index: EmbeddingIndex,
    item_ids: list[int],
    exclude_card_ids: set[int],
    already_shown: set[int],
) -> list[tuple[str, int]]:
    """Nearest RELEVANT corpus cards to a bullet's articles, for the inline 'Related:' line.

    Aggregates index neighbours across the bullet's item_ids (best cosine per neighbour), drops
    anything below the threshold, then keeps up to _INLINE_RELATED_K (title, card_id) pairs
    best-first that are NOT: dismissed, already in this brief (exclude_card_ids), already shown
    in this section (already_shown, mutated for dedupe), or judged out/unjudged. Rejected and
    unjudged cards are deliberately excluded -- the brief is the curated surface and must not
    resurface work the relevance filter dropped.

    Args:
        engine: SQLAlchemy engine (for the effective-relevance filter).
        session: Active session (read-only use).
        index: In-memory embedding index (item_id keyed).
        item_ids: The item ids of the articles this bullet references.
        exclude_card_ids: Card ids already in the brief (featured + listed) -- never "related".
        already_shown: Card ids already shown in this section (mutated for dedupe).

    Returns:
        Up to _INLINE_RELATED_K (title, card_id) tuples, best match first.
    """
    best: dict[int, float] = {}  # neighbour item_id -> best cosine across the bullet's items
    for item_id in item_ids:
        if not index.has(item_id):
            continue
        for neighbour_id, score in index.similar(item_id, k=25):
            if score < _INLINE_RELATED_MIN_COS:
                break  # results are sorted; nothing further can qualify
            if score > best.get(neighbour_id, -1.0):
                best[neighbour_id] = score
    # Candidate (Card, Item) rows in score order, minus dismissed / in-brief / already-shown.
    candidates: list[tuple[Card, Item]] = []
    for neighbour_id, _score in sorted(best.items(), key=lambda kv: kv[1], reverse=True):
        row = session.exec(
            select(Card, Item)
            .where(Card.item_id == Item.id)
            .where(Item.id == neighbour_id)
            .where(Card.state != CardState.DISMISSED)
        ).first()
        if row is None:
            continue
        card, item = row
        if card.id in exclude_card_ids or card.id in already_shown:
            continue
        candidates.append((card, item))
    if not candidates:
        return []
    # Only surface judged, non-out neighbours (a curated brief must not resurface rejected work).
    levels = effective_relevance_map(engine, index, candidates)
    out: list[tuple[str, int]] = []
    for card, item in candidates:
        if levels.get(card.id) in ("low", "medium", "high"):
            out.append((item.title, card.id))
            already_shown.add(card.id)
            if len(out) >= _INLINE_RELATED_K:
                break
    return out


def _build_bullets(
    engine: Engine,
    session: Session,
    index: EmbeddingIndex,
    sections: list[tuple[str, list[str]]],
    featured: list[tuple[Card, Item]],
    listed: list[tuple[Card, Item]],
) -> list[tuple[str, list[Bullet]]]:
    """Turn parsed (heading, [text]) sections into (heading, [Bullet]) with inline related.

    Each bullet's [#n] tokens map to featured items; their nearest OTHER corpus cards become
    the bullet's inline related list, deduped within the section and never including
    a card already in this brief (featured or listed).

    Args:
        session: Active session.
        index: In-memory embedding index.
        sections: Parsed (heading, [bullet_text, ...]) sections.
        featured: (Card, Item) tuples in reference order (item i is token [#i+1]).
        listed: Low-relevance (Card, Item) tuples -- also excluded from related.

    Returns:
        (heading, [Bullet, ...]) sections ready for the renderer.
    """
    featured_item_ids = [item.id for _card, item in featured]
    exclude_card_ids = {card.id for card, _item in featured} | {
        card.id for card, _item in listed
    }
    out: list[tuple[str, list[Bullet]]] = []
    for heading, bullet_texts in sections:
        already_shown: set[int] = set()
        bullets: list[Bullet] = []
        for text in bullet_texts:
            refs = {int(n) for n in _REF_TOKEN.findall(text)}
            item_ids = [featured_item_ids[n - 1] for n in refs if 1 <= n <= len(featured)]
            related = _inline_related_for_bullet(
                engine, session, index, item_ids, exclude_card_ids, already_shown
            )
            bullets.append(Bullet(text=text, related=related))
        out.append((heading, bullets))
    return out


def _validate_partition(sections: list[tuple[str, list[str]]], n_featured: int) -> None:
    """Enforce the one-bullet-per-featured-card partition.

    Goes beyond checking that each [n]/[#n] reference resolves: it enforces a full
    partition over the featured numbers cited across the bullets. For each bullet, the set
    of cited featured numbers is the resolved [n]/[#n] tokens with 1 <= n <= n_featured. All
    three invariants must hold or the brief pauses (nothing is written):

      (a) No duplication -- no featured number appears in >= 2 bullets, so one card can
          never be the main source of several bullets (the over-split symptom: one card
          padded into many duplicate-linked bullets).
      (b) Full coverage -- every featured number 1..n_featured is cited in exactly one
          bullet, so no featured card is silently dropped.
      (c) No fabricated bullet -- every bullet cites >= 1 featured number, so a bullet
          (and its section) is always grounded in a specific featured article.

    Args:
        sections: Parsed (heading, [bullet_text, ...]) sections carrying [n]/[#n] tokens.
        n_featured: Count of featured items; valid featured numbers are 1..n_featured.

    Raises:
        BriefComposeError: Any of (a), (b), (c) is violated.
    """
    # One cited-number set per bullet: the in-range [n]/[#n] tokens it resolves to.
    per_bullet: list[set[int]] = [
        {n for n in (int(m) for m in _REF_TOKEN.findall(text)) if 1 <= n <= n_featured}
        for _heading, texts in sections
        for text in texts
    ]
    # (c) No fabricated bullet: every bullet must be grounded in >= 1 featured article.
    if any(not cited for cited in per_bullet):
        logger.error("brief has a bullet citing no featured article; brief not composed")
        raise BriefComposeError("brief has a bullet that cites no featured article")
    # (a) No duplication: no featured number may be the source of two or more bullets.
    seen: set[int] = set()
    for cited in per_bullet:
        dup = cited & seen
        if dup:
            logger.error("brief duplicates featured card(s) %s across bullets; not composed", dup)
            raise BriefComposeError(
                f"brief duplicates featured card(s) {sorted(dup)} across bullets"
            )
        seen |= cited
    # (b) Full coverage: every featured number 1..n_featured is cited exactly once.
    missing = set(range(1, n_featured + 1)) - seen
    if missing:
        logger.error("brief omits featured card(s) %s; brief not composed", missing)
        raise BriefComposeError(f"brief omits featured card(s) {sorted(missing)} (coverage)")


def narrative_and_markdown(
    engine: Engine,
    index: EmbeddingIndex,
    settings,
    featured: list[tuple[Card, Item]],
    listed: list[tuple[Card, Item]],
    llm: LlmFn | None,
) -> str:
    """LLM narrative over the featured items + deterministic assembly -> brief markdown.

    With featured items: one structured LLM call ({lead, sections}), validated strictly.
    Without: the fixed NO_FEATURED_LEAD line with zero sections (no LLM call at all).
    Either way the References / Also noticed sections are rendered in plain Python.

    Args:
        engine: SQLAlchemy engine.
        index: In-memory embedding index (relevance levels + related links).
        settings: App settings (model, API key, interest note path).
        featured: (Card, Item) tuples in reference order (entry i is token [#i+1]).
        listed: Low-relevance (Card, Item) tuples for the Also-noticed tail.
        llm: Injectable LLM callable (tests); None means the real OpenRouter call.

    Returns:
        The complete brief markdown document.

    Raises:
        BriefComposeError: The LLM call failed or returned a malformed payload.
    """
    if featured:
        interest = read_interest_profile(settings)
        blocks = [
            item_block(
                n + 1, item.title, card.summary,
                card.category, card.tags.split(",") if card.tags else [],
            )
            for n, (card, item) in enumerate(featured)
        ]
        llm = llm or _default_llm(settings)
        try:
            payload = llm(build_brief_messages(interest, blocks))
        except Exception as exc:
            # Pause semantics: surface the failure to the caller; NOTHING is written, so
            # the window and the cards stay intact for a retry once the LLM is back.
            logger.exception("brief narrative LLM call failed; brief not composed")
            raise BriefComposeError(str(exc)) from exc
        lead, sections = parse_brief_payload(payload)
    else:
        lead, sections = NO_FEATURED_LEAD, []  # listed-only brief needs no LLM call

    # Deterministic assembly: effective levels + reference-line backlinks + per-bullet related.
    with Session(engine) as session:
        levels = effective_relevance_map(engine, index, featured)
        names = user_feed_names(session)
        entries = [
            FeaturedEntry(
                card_id=card.id,
                title=item.title,
                # The user's Feeds-tab name, else the stored feed title, else the collector name.
                origin=display_origin(item, names) or item.source,
                # Displayed date is the LOCAL calendar day (machine tz, real
                # today), not the raw naive-UTC date -- a late-UTC-evening story now
                # shows the day a local reader would call "today".
                published=local_day(card, item).isoformat(),
                level=levels.get(card.id) or "medium",
                related=_related_for(session, index, item.id),
            )
            for card, item in featured
        ]
        bullet_sections = _build_bullets(engine, session, index, sections, featured, listed)

        # Partition gate (stricter than checking that each reference resolves):
        # each featured card must be the main source of EXACTLY ONE bullet. Independent of
        # the prompt wording -- pausing beats persisting an over-split brief that fans one
        # card out into many duplicate-linked bullets, or drops a card, or invents a
        # bullet grounded in no article. Only runs when featured is non-empty (the
        # listed-only "Nothing crossed..." path has no featured numbers to partition).
        if featured:
            _validate_partition(sections, len(featured))
    return render_brief_markdown(
        lead, bullet_sections, entries, [(item.title, card.id) for card, item in listed]
    )
