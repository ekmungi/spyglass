"""Which items a brief may show, and which items in its window could not be judged.

News candidates are judged items (tier top, notable or skim) published inside the window.
"From you" candidates are items the reader sent in since the previous brief's cut-off, measured
by when the reader sent them (`ItemState.captured_at`, else the item's fetch time for rows from
before that column existed), whatever their judgement. Items of a feed the reader switched off
are left out, except items the reader sent in. A story is labelled with a watched organisation
only when it names it (`watch.registry.item_is_about`).
"""

from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from spyglass_service.models import Feed, Item
from spyglass_service.radar.brief.cluster import Candidate
from spyglass_service.radar.models import Assessment, ItemEntity, ItemExtra, ItemState, WatchEntity, loads
from spyglass_service.radar.watch.registry import WATCH_SECTION_KINDS, item_is_about

# How far back a published item may be and still count as news for the brief.
CANDIDATE_WINDOW = timedelta(days=4)
# Score given to an item the reader sent in before it has been assessed.
UNASSESSED_FROM_USER_SCORE = 50
# Tiers that make an item news for the brief. "out" is judged irrelevant; "unjudged" (a failed
# triage) is not a judgement at all.
NEWS_TIERS = ("top", "notable", "skim")


def captured_at():
    """SQL expression: when the reader sent the item in (fetch time for older rows)."""
    return func.coalesce(ItemState.captured_at, Item.fetched_at)


def _feed_allowed():
    """SQL condition: not from a switched-off feed, unless the reader sent the item in."""
    return or_(Feed.id.is_(None), Feed.enabled.is_(True), ItemState.from_user.is_(True))


def publication(item: Item) -> str:
    """Name used to count distinct publications: the origin, else the link's host."""
    return (item.origin or urlparse(item.url).netloc or "").strip()


def in_window(item: Item, ref: datetime) -> bool:
    """True when the item's publish (or fetch) time is inside the news window ending at `ref`."""
    moment = item.published_at or item.fetched_at
    return ref - CANDIDATE_WINDOW <= moment <= ref


def safe_count(value: object) -> int:
    """A vote count as an int; text such as "1.2k" or "lots" counts as 0 rather than failing."""
    try:
        return max(0, int(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _upvotes(session: Session, paper_ids: list[int]) -> dict[int, int]:
    """Community upvotes per paper id."""
    if not paper_ids:
        return {}
    rows = session.exec(select(ItemExtra).where(ItemExtra.item_id.in_(paper_ids))).all()
    return {e.item_id: safe_count((loads(e.data, {}) or {}).get("upvotes")) for e in rows}


def _watch_links(session: Session, rows: list[tuple]) -> tuple[dict[int, list], set[int]]:
    """Active watch entities each item is about, and the items about a company or regulator."""
    titles = {item.id: (item.title, a) for item, a, _ in rows}
    links = session.exec(
        select(ItemEntity.item_id, WatchEntity)
        .join(WatchEntity, WatchEntity.id == ItemEntity.entity_id)
        .where(WatchEntity.status == "active", ItemEntity.item_id.in_(list(titles)))
    ).all()
    watch_of: dict[int, list[tuple[str, str]]] = {}
    competitors: set[int] = set()
    for item_id, entity in links:
        title, assessment = titles[item_id]
        if not item_is_about(entity, title, assessment):
            continue  # found by the organisation's search, but not about it
        watch_of.setdefault(item_id, []).append((entity.name, entity.category or ""))
        if entity.kind in WATCH_SECTION_KINDS:
            competitors.add(item_id)
    return watch_of, competitors


def load_candidates(
    session: Session, ref: datetime, skip: set[int], mine_since: datetime, mine_cap: int | None
) -> list[Candidate]:
    """Eligible items as Candidates.

    News candidates are judged items inside the window. "From you" candidates are items the
    reader sent in after `mine_since` (by `captured_at`), kept even when unassessed or judged
    out; `mine_cap` limits them to the newest few. Items in `skip` (shown in an earlier brief)
    are never candidates. A from-user item outside those rules can still appear as ordinary
    news, but without the from-user mark.
    """
    when = func.coalesce(Item.published_at, Item.fetched_at)
    news = and_(Assessment.id.is_not(None), Assessment.tier.in_(NEWS_TIERS),
                when >= ref - CANDIDATE_WINDOW, when <= ref)
    mine = and_(ItemState.from_user.is_(True), captured_at() > mine_since, captured_at() <= ref)
    stmt = (
        select(Item, Assessment, ItemState)
        .outerjoin(Assessment, Assessment.item_id == Item.id)
        .outerjoin(ItemState, ItemState.item_id == Item.id)
        .outerjoin(Feed, Item.feed_url == Feed.feed_url)
        .where(_feed_allowed())
        .where(or_(ItemState.id.is_(None), ItemState.hidden.is_(False)))
        .where(or_(news, mine))
    )
    rows = [r for r in session.exec(stmt).all() if r[0].id not in skip]

    def sent_at(item: Item, state: ItemState) -> datetime:
        """When the reader sent the item in."""
        return state.captured_at.replace(tzinfo=None) if state.captured_at else item.fetched_at

    recent_mine = sorted(
        ((i, st) for i, _, st in rows if st and st.from_user and mine_since < sent_at(i, st) <= ref),
        key=lambda pair: sent_at(*pair), reverse=True,
    )
    keep_mine = {i.id for i, _ in (recent_mine if mine_cap is None else recent_mine[:mine_cap])}
    rows = [
        r for r in rows
        if r[0].id in keep_mine or (r[1] is not None and r[1].tier in NEWS_TIERS and in_window(r[0], ref))
    ]
    upvotes = _upvotes(session, [i.id for i, a, _ in rows if a is not None and a.kind == "paper"])
    watch_of, competitors = _watch_links(session, rows)
    return [_candidate(item, a, item.id in keep_mine, watch_of, competitors, upvotes)
            for item, a, _ in rows]


def _candidate(item: Item, a: Assessment | None, mine: bool, watch_of: dict[int, list],
               competitors: set[int], upvotes: dict[int, int]) -> Candidate:
    """One Candidate from an item row and the lookups built for the whole batch."""
    judged = a is not None and a.tier != "unjudged"
    return Candidate(
        item_id=item.id,
        score=a.score if judged else UNASSESSED_FROM_USER_SCORE,
        when=item.published_at or item.fetched_at,
        publication=publication(item),
        event_key=(a.event_key or None) if a else None,
        kind=a.kind if judged else "news",
        tier=a.tier if judged else "unjudged",
        section=a.section if judged else "",
        from_user=mine,
        watched=item.id in watch_of,
        competitor=item.id in competitors,
        watch=tuple(watch_of.get(item.id, ())),
        upvotes=upvotes.get(item.id, 0),
        url=item.url,
    )


def unjudged_ids(session: Session, since: datetime, ref: datetime) -> set[int]:
    """Items collected in (since, ref] that have no usable judgement.

    That is no assessment at all, or a failed triage (tier "unjudged"). Items of a switched-off
    feed are skipped on purpose by the pipeline, so they are not counted, unless the reader
    sent them in.
    """
    stmt = (
        select(Item.id)
        .outerjoin(Assessment, Assessment.item_id == Item.id)
        .outerjoin(ItemState, ItemState.item_id == Item.id)
        .outerjoin(Feed, Item.feed_url == Feed.feed_url)
        .where(Item.fetched_at > since, Item.fetched_at <= ref, _feed_allowed())
        .where(or_(Assessment.id.is_(None), Assessment.tier == "unjudged"))
    )
    return set(session.exec(stmt).all())
