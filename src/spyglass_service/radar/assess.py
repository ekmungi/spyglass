"""Judge items against the reader's profile in two stages and store each judgement.

Triage scores up to 20 items per model call from title, publication and snippet. Items that
pass the gate, and every item the reader sent in, are then digested: their text is fetched
(through the reader package when it is installed), read, and given a headline, a line on why it
matters, key points, entities and an event key. Every item's Assessment is committed on its
own, so a crash loses at most the item in flight. The model call is injectable (`llm`), so
tests never touch the network.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from spyglass_service.content_store import get_fulltext
from spyglass_service.models import Feed, Item
from spyglass_service.radar.assess_prompt import (
    TEXT_CHARS,
    DigestResult,
    TriageResult,
    build_digest_messages,
    build_triage_messages,
    clean_snippet,
    digest_schema,
    parse_digest,
    parse_triage,
    plain_title,
    tier_for,
    triage_row,
    triage_schema,
)
from spyglass_service.radar.assess_attempts import (
    failure_fields,
    record_digest_failure,
    record_triage_failure,
)
from spyglass_service.radar.llm import LlmUnavailable, chat_json_for, model_for
from spyglass_service.radar.models import Assessment, ItemState, dumps, utcnow
from spyglass_service.radar.profile import (
    get_profile,
    profile_prompt_block,
    refresh_examples,
    section_keys,
)

logger = logging.getLogger(__name__)

# (messages, json schema, model id) -> parsed JSON object. The real one calls OpenRouter.
LlmFn = Callable[[list[dict], dict, str], dict]
# Makes sure an item's text is stored in the Content table (or tries to); returns nothing.
FetchFn = Callable[[int], None]

# Items per triage call: large enough to amortise the prompt, small enough to stay reliable.
TRIAGE_BATCH = 20
# Exceptions that mean "the model answered, but not with usable JSON".
_MALFORMED = (ValueError, KeyError, TypeError, IndexError)


@dataclass(frozen=True)
class Judge:
    """What every judgement in one run shares: the model call, the profile text and settings."""

    llm: LlmFn
    block: str
    keys: list[str]
    version: int
    triage_model: str
    digest_model: str
    gate: int


@dataclass(frozen=True)
class TriageOutcome:
    """Result of triaging a list of rows.

    results: judged items. errors: id -> reason, for items whose reply was missing or malformed
    twice. unreachable: ids left unjudged because the model could not be reached.
    """

    results: dict[int, TriageResult] = field(default_factory=dict)
    errors: dict[int, str] = field(default_factory=dict)
    unreachable: list[int] = field(default_factory=list)


def default_llm(settings) -> LlmFn:
    """The real model call: every provider goes through the seam in `radar.llm`.

    That keeps the fallback order, the privacy scrub and the web-text fence in force. Without a
    `role`, the triage model's id means triage and anything else digest.
    """

    def call(messages: list[dict], schema: dict, model: str, role: str | None = None) -> dict:
        """Make one structured-output request through the seam and return the parsed object."""
        chosen = role or ("triage" if model == model_for(settings, "triage") else "digest")
        return chat_json_for(settings, chosen, messages, schema, model=model)

    call.takes_role = True  # type: ignore[attr-defined]  # see `_call`
    return call


def make_judge(engine: Engine, settings, *, llm: LlmFn | None = None) -> Judge:
    """Build the run's Judge from the stored profile and the reader's history."""
    with Session(engine) as session:
        profile = get_profile(session)
        examples = refresh_examples(session, settings=settings)
    return Judge(
        llm=llm or default_llm(settings),
        block=profile_prompt_block(profile, examples),
        keys=section_keys(profile),
        version=int(profile.get("version") or 0),
        triage_model=model_for(settings, "triage"),
        digest_model=model_for(settings, "digest"),
        gate=int(settings.radar_digest_gate),
    )


def _call(llm: LlmFn, messages: list[dict], schema: dict, model: str, role: str) -> dict:
    """Call the model; ValueError for an unusable reply, LlmUnavailable for no reply at all.

    `role` goes only to a call that says it takes one (`default_llm`'s); test fakes keep three arguments.
    """
    try:
        raw = (llm(messages, schema, model, role=role) if getattr(llm, "takes_role", False)  # type: ignore[call-arg]
               else llm(messages, schema, model))
    except _MALFORMED as exc:
        raise ValueError(f"unusable reply: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 -- any transport failure means "try again later"
        raise LlmUnavailable(str(exc)) from exc
    if not isinstance(raw, dict):
        raise ValueError("reply is not a JSON object")
    return raw


def _chunks(rows: list[dict], size: int) -> Iterator[list[dict]]:
    """Consecutive slices of `rows` of at most `size`."""
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def _triage_batch(judge: Judge, batch: list[dict]) -> tuple[dict[int, TriageResult], list[int]]:
    """One triage call; returns (results, ids missing or malformed). Raises LlmUnavailable."""
    ids = [row["id"] for row in batch]
    messages = build_triage_messages(judge.block, batch)
    try:
        raw = _call(judge.llm, messages, triage_schema(judge.keys), judge.triage_model,
                    "triage")
    except ValueError:
        return {}, ids
    return parse_triage(raw, ids, judge.keys)


def triage_rows(judge: Judge, rows: list[dict]) -> TriageOutcome:
    """Triage rows (see `triage_row`) in batches; no database access.

    A row missing or malformed in a batch reply is retried alone once, then reported in
    `errors`. When a whole batch call fails and the first solo retry fails too, the model is
    treated as unreachable and the rest of that batch is left for a later run.
    """
    outcome = TriageOutcome()
    for batch in _chunks(rows, TRIAGE_BATCH):
        batch_failed = False
        try:
            got, bad = _triage_batch(judge, batch)
        except LlmUnavailable as exc:
            logger.warning("triage batch of %d failed: %s", len(batch), exc)
            got, bad, batch_failed = {}, [row["id"] for row in batch], True
        outcome.results.update(got)
        retry = [row for row in batch if row["id"] in bad]
        for position, row in enumerate(retry):
            try:
                solo, still_bad = _triage_batch(judge, [row])
            except LlmUnavailable:
                if batch_failed and position == 0:
                    outcome.unreachable.extend(r["id"] for r in retry)
                    break
                outcome.unreachable.append(row["id"])
                continue
            outcome.results.update(solo)
            if still_bad:
                outcome.errors[row["id"]] = "triage failed: reply missing or malformed twice"
    return outcome


def disabled_feed_urls(session: Session) -> set[str]:
    """Feed URLs the reader switched off."""
    return set(session.exec(select(Feed.feed_url).where(Feed.enabled == False)).all())  # noqa: E712


def from_user_ids(session: Session, item_ids: list[int]) -> set[int]:
    """Which of `item_ids` the reader sent in."""
    if not item_ids:
        return set()
    rows = session.exec(
        select(ItemState.item_id)
        .where(ItemState.item_id.in_(item_ids), ItemState.from_user == True)  # noqa: E712
    ).all()
    return set(rows)


def store_assessment(engine: Engine, item_id: int, fields: dict) -> None:
    """Create or update the item's Assessment with `fields` and commit it on its own."""
    with Session(engine) as session:
        row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
        row = row or Assessment(item_id=item_id)
        for name, value in fields.items():
            setattr(row, name, value)
        row.assessed_at = utcnow()
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            # Another writer created the row between our read and commit: update theirs.
            session.rollback()
            existing = session.exec(select(Assessment).where(Assessment.item_id == item_id)).one()
            for name, value in fields.items():
                setattr(existing, name, value)
            session.add(existing)
            session.commit()


def triage_fields(judge: Judge, result: TriageResult | None, error: str | None,
                  from_user: bool) -> dict:
    """Assessment columns for a triage-stage judgement (digest columns are cleared).

    `result` None records a failed triage: stage "triage_failed", tier "unjudged" and the
    reason in `error` (never in `why`, which the reader sees). Callers that store a failure use
    `assess_attempts.record_triage_failure`, which also counts the attempt.
    """
    if result is None:
        return failure_fields(judge.triage_model, judge.version, error or "triage failed")
    return {
        "stage": "triage", "score": result.score,
        "tier": tier_for(result.score, from_user=from_user), "section": result.section,
        "kind": result.kind, "headline": None, "why": None, "key_points": None,
        "entities": None, "event_key": None, "model": judge.triage_model,
        "profile_version": judge.version, "error": None, "digest_attempts": 0,
    }


def _usable(stored: dict | None) -> bool:
    """True when stored content holds readable text."""
    return bool(stored and stored.get("status") == "ok" and (stored.get("markdown") or "").strip())


def fetch_text(engine: Engine, settings, item_id: int) -> None:
    """Default fetch: the reader package's document builder, else the engine's fetch ladder.

    The reader builder stores plain text in the Content table as a side effect. When that
    package is missing or raises, the URL is fetched by `assess_fetch.plain_fetch`. A Google News
    redirect address is first replaced by the publisher's own address, which the reader can fetch.
    """
    from spyglass_service.radar.sources.google_links import resolve_item_url

    resolve_item_url(engine, item_id)
    try:
        from spyglass_service.radar.reader.build import ensure_reader_doc
    except ImportError:
        ensure_reader_doc = None
    if ensure_reader_doc is not None:
        try:
            ensure_reader_doc(engine, settings, item_id)
            return
        except Exception:  # noqa: BLE001 -- fall back to the plain fetch below
            logger.warning("reader build failed for item %s; using plain fetch", item_id,
                           exc_info=True)
    from spyglass_service.radar.assess_fetch import plain_fetch

    plain_fetch(engine, settings, item_id)


def item_text(engine: Engine, item_id: int, fetch: FetchFn) -> str:
    """The item's stored full text, fetching it first when nothing usable is stored."""
    stored = get_fulltext(engine, item_id)
    if not _usable(stored):
        try:
            fetch(item_id)
        except Exception:  # noqa: BLE001 -- a failed fetch falls back to the feed snippet
            logger.warning("fetch failed for item %s", item_id, exc_info=True)
        stored = get_fulltext(engine, item_id)
    return stored["markdown"][:TEXT_CHARS] if _usable(stored) else ""


def _digest_fields(judge: Judge, result: DigestResult, from_user: bool) -> dict:
    """Assessment columns for a digest-stage judgement."""
    return {
        "stage": "digest", "score": result.score,
        "tier": tier_for(result.score, from_user=from_user), "section": result.section,
        "kind": result.kind, "headline": result.headline, "why": result.why or None,
        "key_points": dumps(list(result.key_points)), "entities": dumps(list(result.entities)),
        "event_key": result.event_key or None, "model": judge.digest_model,
        "profile_version": judge.version,
    }


def _embed(engine: Engine, index, item: Item, result: DigestResult) -> None:
    """Replace the item's vector with one built from its digest; failures only log."""
    from spyglass_service.embeddings import embed_summary

    try:
        summary = " ".join([result.headline, *result.key_points])
        embed_summary(engine, index, item.id, item.title, summary, list(result.entities))
    except Exception:  # noqa: BLE001 -- the digest is stored; the vector is a backfillable extra
        logger.warning("embedding failed for item %s", item.id, exc_info=True)


def digest_one(engine: Engine, settings, judge: Judge, item_id: int, *,
               fetch: FetchFn | None = None, index=None) -> DigestResult | None:
    """Read one item's text, write its digest and store it.

    Returns the DigestResult, or None when the item does not exist or the reply was unusable
    twice (the triage judgement is then kept). Raises LlmUnavailable when the model cannot be
    reached, so the caller can count it and retry on a later run.
    """
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            return None
        session.expunge(item)
        from_user = item_id in from_user_ids(session, [item_id])
    text = item_text(engine, item_id, fetch or (lambda i: fetch_text(engine, settings, i)))
    if not text:
        # No full text: judge the feed's own summary, and say so to the model.
        snippet = clean_snippet(item.summary, TEXT_CHARS) or item.title
        text = f"(Only the feed's short summary is available.)\n{snippet}"
    meta = {"title": plain_title(item.title), "publication": item.origin or "",
            "source": item.source, "url": item.url}
    messages = build_digest_messages(judge.block, meta, text)
    schema = digest_schema(judge.keys)
    result: DigestResult | None = None
    problem = ""
    for attempt in (1, 2):
        try:
            raw = _call(judge.llm, messages, schema, judge.digest_model, "digest")
            result = parse_digest(raw, judge.keys)
            break
        except ValueError as exc:
            problem = str(exc)
            logger.warning("digest reply for item %s unusable (attempt %d): %s",
                           item_id, attempt, exc)
    if result is None:
        # Counted, so the pipeline stops re-fetching and re-asking after a few runs. An outage
        # never reaches this line: LlmUnavailable propagates to the caller uncounted.
        record_digest_failure(engine, item_id, f"digest reply unusable: {problem}")
        return None
    store_assessment(engine, item_id, _digest_fields(judge, result, from_user))
    if index is not None:
        _embed(engine, index, item, result)
    return result


def _summary(engine: Engine, item_id: int) -> dict | None:
    """Small dict describing the stored assessment of an item, or None when there is none."""
    with Session(engine) as session:
        row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
        if row is None:
            return None
        return {"item_id": item_id, "stage": row.stage, "score": row.score, "tier": row.tier,
                "section": row.section, "kind": row.kind, "headline": row.headline}


def assess_one(engine: Engine, settings, item_id: int, *, force: bool = False,
               llm: LlmFn | None = None, fetch: FetchFn | None = None, index=None) -> dict | None:
    """Assess one item now: triage, then digest when it passes the gate or the reader sent it.

    Without `force`, an item already digested (or triaged below the gate) is returned as
    stored. Items from a feed the reader switched off are skipped unless the reader sent them.
    Returns the stored assessment summary, {"item_id", "skipped": reason}, or None when the item
    does not exist. Raises LlmUnavailable when the model cannot be reached.
    """
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            return None
        from_user = item_id in from_user_ids(session, [item_id])
        if not from_user and item.feed_url and item.feed_url in disabled_feed_urls(session):
            return {"item_id": item_id, "skipped": "feed disabled"}
        existing = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
        stage, score = (existing.stage, existing.score) if existing else (None, 0)
    judge = make_judge(engine, settings, llm=llm)
    if force or existing is None or stage == "triage_failed":
        outcome = triage_rows(judge, [triage_row(item.id, item.title, item.origin, item.source,
                                                 item.summary)])
        if outcome.unreachable:
            raise LlmUnavailable(f"model unreachable while triaging item {item_id}")
        result = outcome.results.get(item_id)
        if result is None:
            record_triage_failure(engine, item_id, outcome.errors.get(item_id) or "triage failed",
                                  model=judge.triage_model, profile_version=judge.version)
            stage, score = "triage_failed", 0
        else:
            store_assessment(engine, item_id, triage_fields(judge, result, None, from_user))
            stage, score = "triage", result.score
    # A reader's item is digested even when its triage failed: the digest gives its own score.
    if stage in ("triage", "triage_failed") and (from_user or score >= judge.gate):
        digest_one(engine, settings, judge, item_id, fetch=fetch, index=index)
    return _summary(engine, item_id)
