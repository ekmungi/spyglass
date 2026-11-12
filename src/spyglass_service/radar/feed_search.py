"""Find the feed items that are close to a piece of text or to another item.

Used by the "Related" filter on the Feed, by the reader's "Show related in the Feed" entry and by
the feed-wide assistant. Candidates come from three places and are merged:

1. the embedding index (cosine similarity to the embedded text, or to the item's own vector),
2. stored full text (the full-text index), and
3. case-insensitive matches of the words in an item's title or rewritten headline.

Items judged "out" and items from switched-off feeds are dropped. The rank is a simple blend: the
semantic similarity first, a small bonus for a text hit and a small bonus for recency.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from spyglass_service.content_store import search_fulltext
from spyglass_service.models import Feed, Item
from spyglass_service.radar.models import Assessment

logger = logging.getLogger(__name__)

# How many nearest vectors are read before filtering. Generous, because the filters below
# (tier "out", muted feeds, the day window) drop some of them.
_NEAREST_MIN = 120
# The built-in embedding model (snowflake arctic) packs cosine similarities into a narrow band
# and expects a prefix on search queries. Measured on a real feed: a question unrelated to
# anything scores 0.55 to 0.61 against the best item, a topical question 0.65 to 0.80, and an
# item's neighbours 0.70 to 0.89. So with this model a question needs 0.62 and a neighbour 0.70;
# any other model keeps the general default of 0.45.
ARCTIC_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_FLOOR = 0.45
ARCTIC_QUERY_FLOOR = 0.62
ARCTIC_NEIGHBOUR_FLOOR = 0.70
# Weight of a text hit, and of recency, next to a similarity that lies between 0 and 1.
TEXT_BONUS = 0.15
RECENCY_BONUS = 0.05
# Items older than this get no recency bonus.
RECENCY_DAYS = 30
# Most words used for the text search, and most hits read from each text source.
_KEYWORDS_MAX = 8
_TEXT_LIMIT = 100
# Tiers a "recent and important" listing draws from, best first.
_RECENT_TIERS = ("top", "notable", "skim")

# Words that carry no topic, so a question like "What do I have about X?" searches for X only.
_STOPWORDS = frozenset(
    "a about all also an and any are as at be been but by can could did do does for from get give "
    "had has have how i if in into is it its me more most my of on or our out over show so some "
    "tell than that the their them then there these they this those to up was we were what when "
    "where which who why will with would you your anything something everything feed items item "
    "articles article stuff papers paper news".split()
)
_WORD = re.compile(r"[^\W_]{3,}(?:-[^\W_]+)*", re.UNICODE)


def _is_arctic(index) -> bool:
    """True for the built-in embedding model, whose scores and query prefix differ (see above)."""
    return "arctic" in str(getattr(index, "model", "")).lower()


def _query_vector(index, query: str):
    """The embedded search query, with the model's query prefix when it needs one."""
    return index.embed_query(ARCTIC_QUERY_PREFIX + query if _is_arctic(index) else query)


def query_vector(index, query: str):
    """The embedded question, with the model's query prefix when it needs one (for other modules)."""
    return _query_vector(index, query)


def keywords(text: str) -> list[str]:
    """The distinctive words of a question, in order, without filler words (at most eight)."""
    seen: list[str] = []
    for word in _WORD.findall((text or "").lower()):
        if word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen[:_KEYWORDS_MAX]


def _naive_utc(value: datetime) -> datetime:
    """A timestamp as the naive UTC that the database stores."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _now() -> datetime:
    """The current time as naive UTC."""
    return _naive_utc(datetime.now(UTC))


def _text_hits(session: Session, words: list[str]) -> set[int]:
    """Ids of items whose stored text, title or headline contains all of `words`.

    Falls back to the three longest words when all of them together match nothing, because a
    question often holds one word that the items never use.
    """
    if not words:
        return set()
    for attempt in (words, sorted(words, key=len, reverse=True)[:3] if len(words) > 3 else None):
        if not attempt:
            continue
        found = _title_hits(session, attempt)
        try:
            found |= {h["item_id"] for h in search_fulltext(
                session.get_bind(), " ".join(attempt).replace('"', " "), limit=_TEXT_LIMIT)}
        except OperationalError:
            logger.warning("full-text search failed for %r; using title matches only", attempt)
        if found:
            return found
    return set()


def _title_hits(session: Session, words: list[str]) -> set[int]:
    """Ids whose title or rewritten headline contains every word, ignoring case."""
    stmt = (select(Item.id).select_from(Item)
            .join(Assessment, Assessment.item_id == Item.id, isouter=True))
    for word in words:
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(Item.title.ilike(like, escape="\\"),
                              Assessment.headline.ilike(like, escape="\\")))
    return set(session.exec(stmt.limit(_TEXT_LIMIT)).all())


def _allowed(session: Session, ids: list[int], days: int | None) -> dict[int, datetime]:
    """For the ids that may be shown: item id -> its date (published, else fetched).

    Drops tier "out", items from switched-off feeds, and items older than `days`.
    """
    if not ids:
        return {}
    when = func.coalesce(Item.published_at, Item.fetched_at)
    rows = session.exec(
        select(Item.id, when, Assessment.tier, Feed.enabled).select_from(Item)
        .join(Assessment, Assessment.item_id == Item.id, isouter=True)
        .join(Feed, Feed.feed_url == Item.feed_url, isouter=True)
        .where(Item.id.in_(ids))).all()
    cutoff = _now() - timedelta(days=days) if days else None
    allowed: dict[int, datetime] = {}
    for item_id, moment, tier, enabled in rows:
        if tier == "out" or enabled is False:
            continue
        stamp = moment if isinstance(moment, datetime) else datetime.fromisoformat(str(moment))
        stamp = _naive_utc(stamp)
        if cutoff and stamp < cutoff:
            continue
        allowed[item_id] = stamp
    return allowed


def _recency(stamp: datetime) -> float:
    """1.0 for an item from now, falling to 0.0 at `RECENCY_DAYS` days old."""
    age_days = max(0.0, (_now() - stamp).total_seconds() / 86400)
    return max(0.0, 1.0 - age_days / RECENCY_DAYS)


def _rank(session: Session, similarity: dict[int, float], text: set[int], *, days: int | None,
          floor: float, limit: int, exclude: int | None = None) -> list[tuple[int, float]]:
    """Merge semantic and text candidates, filter them and return the best `limit`."""
    candidates = {i for i, s in similarity.items() if s >= floor} | text
    candidates.discard(exclude)
    allowed = _allowed(session, sorted(candidates), days)
    scored: list[tuple[int, float]] = []
    for item_id, stamp in allowed.items():
        score = (max(0.0, similarity.get(item_id, 0.0))
                 + (TEXT_BONUS if item_id in text else 0.0)
                 + RECENCY_BONUS * _recency(stamp))
        scored.append((item_id, score))
    # Sort on the full blend; only the number shown is capped at 1, so the best items never tie.
    scored.sort(key=lambda pair: (-pair[1], -pair[0]))
    return [(i, round(min(s, 1.0), 4)) for i, s in scored[:limit]]


def _similarities(index, text_ids: set[int], vector) -> dict[int, float]:
    """Cosine of `vector` to the stored vectors of the text hits (so they rank by closeness too)."""
    found, matrix = index.matrix_for(sorted(text_ids))
    return {i: float(row @ vector) for i, row in zip(found, matrix, strict=False)}


def related_items(session: Session, index, text: str, *, limit: int = 30,
                  min_similarity: float | None = None, days: int | None = None) -> list[tuple[int, float]]:
    """Feed items related to `text`, best first, as (item id, score between 0 and 1).

    `index` is the embedding index or None (then only text matches are used). A failing
    embedding step is logged and the text matches still answer. Items below `min_similarity`
    (default: 0.62 for the built-in model, else 0.45) are kept only when their words match.
    """
    query = " ".join((text or "").split())
    if not query:
        return []
    similarity: dict[int, float] = {}
    vector = None
    if index is not None:
        try:
            vector = _query_vector(index, query)
            similarity = dict(index.nearest(vector, max(_NEAREST_MIN, limit * 4)))
        except Exception:  # noqa: BLE001 -- the index is optional; text search still answers
            logger.exception("semantic search failed; using text matches only")
            vector = None
    text_ids = _text_hits(session, keywords(query))
    if vector is not None and text_ids:
        similarity = {**_similarities(index, text_ids, vector), **similarity}
    floor = min_similarity if min_similarity is not None else (
        ARCTIC_QUERY_FLOOR if _is_arctic(index) else DEFAULT_FLOOR)
    return _rank(session, similarity, text_ids, days=days, floor=floor, limit=limit)


def related_to_item(session: Session, index, item_id: int, *, limit: int = 30,
                    min_similarity: float | None = None,
                    days: int | None = None) -> list[tuple[int, float]]:
    """Feed items close to one item's own vector (never the item itself), best first.

    Returns [] when the index is missing or has no vector for the item. The default floor is 0.70
    for the built-in model (else 0.45).
    """
    if index is None:
        return []
    found, matrix = index.matrix_for([item_id])
    if not found:
        return []
    similarity = dict(index.nearest(matrix[0], max(_NEAREST_MIN, limit * 4)))
    floor = min_similarity if min_similarity is not None else (
        ARCTIC_NEIGHBOUR_FLOOR if _is_arctic(index) else DEFAULT_FLOOR)
    return _rank(session, similarity, set(), days=days, floor=floor, limit=limit, exclude=item_id)


def recent_items(session: Session, *, days: int = 7, limit: int = 25) -> list[tuple[int, float]]:
    """The strongest items of the last `days` days, by relevance score then recency.

    Returns (item id, score between 0 and 1) for tiers top, notable and skim only.
    """
    cutoff = _now() - timedelta(days=days)
    when = func.coalesce(Item.published_at, Item.fetched_at)
    rows = session.exec(
        select(Item.id, Assessment.score).select_from(Item)
        .join(Assessment, Assessment.item_id == Item.id)
        .join(Feed, Feed.feed_url == Item.feed_url, isouter=True)
        .where(Assessment.tier.in_(_RECENT_TIERS), when >= cutoff,
               or_(Item.feed_url.is_(None), Feed.id.is_(None), Feed.enabled == True))  # noqa: E712
        .order_by(Assessment.score.desc(), when.desc(), Item.id.desc()).limit(limit)).all()
    return [(item_id, round(min(1.0, (score or 0) / 100), 4)) for item_id, score in rows]
