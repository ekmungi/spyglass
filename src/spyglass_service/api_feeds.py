"""Feeds REST API: CRUD + import/export endpoints for managing RSS/Atom subscriptions."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, func, select

from spyglass_service.feed_discovery import DiscoverResult, discover
from spyglass_service.feed_io import OPMLParseError, build_markdown, build_opml, parse_opml
from spyglass_service.feed_registry import NotAFeedError, add_feed, delete_feed, get_feed, list_feeds, update_feed
from spyglass_service.lifecycle import delete_cards
from spyglass_service.models import Card, Feed, Item

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class FeedOut(BaseModel):
    """Serialised view of a Feed row, including derived item_count."""

    id: int
    feed_url: str
    name: str
    name_overridden: bool
    kind: str
    enabled: bool
    last_fetch_status: str | None
    last_fetch_at: datetime | None
    last_error: str | None
    item_count: int
    added_via: str


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class AddFeedBody(BaseModel):
    """Body for POST /api/feeds: the URL to subscribe to plus an optional friendly name.

    Attributes:
        url: The feed URL to resolve and register.
        name: Optional friendly display name.  When provided and non-empty, the stored
            feed name is set to this value and name_overridden is marked True so that
            periodic title re-resolution will not clobber it.  When absent or empty,
            the name is derived from the feed's own title element.
    """

    url: str
    name: str | None = None


class PatchFeedBody(BaseModel):
    """Body for PATCH /api/feeds/{id}: partial update (enabled and/or name)."""

    enabled: bool | None = None
    name: str | None = None


class DiscoverBody(BaseModel):
    """Body for POST /api/feeds/discover: the page URL and discovery depth."""

    url: str
    depth: int = 0


class CandidateOut(BaseModel):
    """Serialised Candidate for the discover endpoint response."""

    feed_url: str
    name: str
    kind: str
    already_subscribed: bool


class DiscoverOut(BaseModel):
    """Response shape for POST /api/feeds/discover.

    Attributes:
        candidates: Validated feed candidates (empty on failure).
        reason: Human-readable explanation when candidates is empty.
        reason_code: Machine-readable failure code, or None when candidates is
            non-empty.  Values: 'blocked', 'not_html', 'too_large', 'http_error',
            'network_error', 'no_feeds'.
    """

    candidates: list[CandidateOut]
    reason: str | None
    reason_code: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _item_count_map(session: Session) -> dict[str, int]:
    """Build a feed_url -> item_count mapping in a single COUNT query.

    Groups Item rows by feed_url; only rows where feed_url is non-null contribute.
    Feeds with zero items simply won't appear in the result, handled in _feed_out.

    Args:
        session: Active SQLModel session.

    Returns:
        Mapping of feed_url to the count of associated Item rows.
    """
    rows = session.exec(
        select(Item.feed_url, func.count(Item.id)).where(Item.feed_url.isnot(None)).group_by(Item.feed_url)  # type: ignore[union-attr]
    ).all()
    return {feed_url: count for feed_url, count in rows}


def _feed_out(feed: Feed, counts: dict[str, int]) -> FeedOut:
    """Construct a FeedOut from a Feed row and a pre-built count map.

    Args:
        feed: Feed ORM instance (must have an id).
        counts: Mapping of feed_url -> item_count (from _item_count_map).

    Returns:
        FeedOut pydantic model populated from the feed row.
    """
    return FeedOut(
        id=feed.id,  # type: ignore[arg-type]
        feed_url=feed.feed_url,
        name=feed.name,
        name_overridden=feed.name_overridden,
        kind=feed.kind,
        enabled=feed.enabled,
        last_fetch_status=feed.last_fetch_status,
        last_fetch_at=feed.last_fetch_at,
        last_error=feed.last_error,
        item_count=counts.get(feed.feed_url, 0),
        added_via=feed.added_via,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/feeds")
def list_feeds_endpoint(request: Request) -> list[FeedOut]:
    """Return all registered feeds with a derived item_count per feed.

    item_count is the number of Item rows whose feed_url matches Feed.feed_url.
    Feeds with no collected items report item_count=0.
    """
    with Session(request.app.state.engine) as session:
        feeds = list_feeds(session)
        counts = _item_count_map(session)
    return [_feed_out(f, counts) for f in feeds]


@router.post("/feeds")
def add_feed_endpoint(request: Request, body: AddFeedBody) -> FeedOut:
    """Register a new feed by URL.

    Resolves the URL, validates it as a parseable RSS/Atom feed, dedupes on the
    resolved URL, and inserts the row. Returns the FeedOut on success.

    Raises:
        HTTPException 422: When the URL cannot be read as a feed.
            Body: {"kind": "not_a_feed" | "blocked" | "unreachable", "url": <resolved_url>,
            "reason": <plain sentence>}
    """
    with Session(request.app.state.engine) as session:
        try:
            feed = add_feed(session, body.url, name=body.name)
        except NotAFeedError as exc:
            raise HTTPException(
                status_code=422,
                detail={"kind": exc.kind, "url": exc.url, "reason": exc.reason},
            ) from exc
        counts = _item_count_map(session)
        return _feed_out(feed, counts)


@router.patch("/feeds/{feed_id}")
def patch_feed_endpoint(request: Request, feed_id: int, body: PatchFeedBody) -> FeedOut:
    """Partially update a feed's enabled flag and/or display name.

    Providing name sets name_overridden=True so periodic title re-resolution does
    not clobber the user's custom label.

    Raises:
        HTTPException 404: When feed_id does not exist.
    """
    with Session(request.app.state.engine) as session:
        feed = update_feed(session, feed_id, enabled=body.enabled, name=body.name)
        if feed is None:
            raise HTTPException(status_code=404, detail="feed not found")
        counts = _item_count_map(session)
        return _feed_out(feed, counts)


@router.delete("/feeds/{feed_id}")
def delete_feed_endpoint(request: Request, feed_id: int) -> dict:
    """Hard-delete a feed and all its collected cards/items.

    Deletion sequence (tombstone semantics):
    1. Look up the feed; 404 if absent.
    2. Find all Card ids whose Item.feed_url matches the feed's feed_url.
    3. Call delete_cards() to tombstone each item and remove card/item/content/embedding rows.
    4. Remove the feed from the reader tracking DB (tolerates FeedNotFoundError).
    5. Drop the Feed row from the application DB.

    Returns:
        {"deleted": True, "cards_removed": <n>}

    Raises:
        HTTPException 404: When feed_id does not exist.
    """
    engine = request.app.state.engine
    settings = request.app.state.settings
    index = request.app.state.service_state.ensure_index()

    with Session(engine) as session:
        feed = get_feed(session, feed_id)
        if feed is None:
            raise HTTPException(status_code=404, detail="feed not found")
        feed_url = feed.feed_url

        # Collect all card ids for items belonging to this feed.
        card_ids: list[int] = list(
            session.exec(
                select(Card.id)
                .join(Item, Card.item_id == Item.id)
                .where(Item.feed_url == feed_url)
            ).all()
        )

    # Tombstone + purge cards/items. delete_cards handles unknown ids safely.
    result = delete_cards(engine, settings, card_ids, index=index)
    cards_removed: int = result["deleted"]

    # Remove the feed from the reader tracking DB so it stops being collected.
    try:
        from reader import make_reader  # noqa: PLC0415

        reader_db = str(settings.data_dir / "reader.db")
        with make_reader(reader_db) as reader_instance:
            reader_instance.delete_feed(feed_url)
    except Exception:  # noqa: BLE001
        # FeedNotFoundError or any IO error: reader didn't know this feed, safe to ignore.
        pass

    # Drop the Feed row from the application DB.
    with Session(engine) as session:
        delete_feed(session, feed_id)

    return {"deleted": True, "cards_removed": cards_removed}


# ---------------------------------------------------------------------------
# Feed discovery
# ---------------------------------------------------------------------------


@router.post("/feeds/discover")
def discover_feeds_endpoint(request: Request, body: DiscoverBody) -> DiscoverOut:
    """Discover feed candidates for a given page URL (user-initiated, bounded, on-demand).

    Shallow (depth=0): parses declared <link rel=alternate rss/atom> tags.
    Deep (depth=1): also probes common feed paths + crawls in-page section links
    one level.  Each candidate is validated as a parseable feed before being
    returned; the already_subscribed flag is set when the candidate is already
    registered.

    Bounds enforced: one page, one level, ~25 links, ~2 MB body cap, per-request
    connect/read timeouts.  Dead sites / non-HTML / oversized pages return an
    empty candidate list with a descriptive reason.  Never raises to the client.

    Args:
        body: DiscoverBody with url and depth (0=shallow, 1=deep).

    Returns:
        DiscoverOut with candidates list and optional reason string.
    """
    with Session(request.app.state.engine) as session:
        registered_urls: set[str] = {f.feed_url for f in list_feeds(session)}

    result: DiscoverResult = discover(body.url, body.depth, registry_urls=registered_urls)

    return DiscoverOut(
        candidates=[
            CandidateOut(
                feed_url=c.feed_url,
                name=c.name,
                kind=c.kind,
                already_subscribed=c.already_subscribed,
            )
            for c in result.candidates
        ],
        reason=result.reason,
        reason_code=result.reason_code,
    )


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


@router.post("/feeds/import")
async def import_feeds_endpoint(request: Request) -> dict[str, int]:
    """Import feeds from an OPML or markdown document sent as a plain-text request body.

    Format detection: if the body starts with '<' the content is treated as OPML and
    parsed with parse_opml; otherwise it is treated as a markdown feed list and parsed
    with parse_feed_list. Each resolved URL is passed to add_feed; already-registered
    URLs are counted as skipped rather than added.

    Body shape: raw ``text/plain`` (or any content-type) — the entire request body is
    read as UTF-8 text. The frontend should send the file's text content directly.

    Returns:
        ``{"added": <n>, "skipped": <n>}`` where added is newly inserted feeds and
        skipped is the count of duplicates plus URLs that are not valid feeds.

    Raises:
        HTTPException 422: When the body is OPML-shaped but cannot be parsed as XML.
    """
    from spyglass_service.collectors.feedlist import parse_feed_list  # noqa: PLC0415
    from spyglass_service.collectors.rss import resolve_feed_url  # noqa: PLC0415

    body_bytes = await request.body()
    text = body_bytes.decode("utf-8", errors="replace").strip()

    # Detect format by inspecting the first non-whitespace character.
    if text.startswith("<"):
        try:
            urls = parse_opml(text)
        except OPMLParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        urls = parse_feed_list(text)

    added = 0
    skipped = 0

    with Session(request.app.state.engine) as session:
        for url in urls:
            # Check pre-existence to distinguish "already registered" from "newly added".
            # add_feed resolves the URL first; mirror that resolution for the pre-check.
            resolved = resolve_feed_url(url)
            already_exists = (
                session.exec(select(Feed).where(Feed.feed_url == resolved)).first() is not None
            )

            if already_exists:
                skipped += 1
                continue

            try:
                add_feed(session, url)
                added += 1
            except NotAFeedError:
                skipped += 1

    return {"added": added, "skipped": skipped}


_SUPPORTED_EXPORT_FORMATS = {"opml", "markdown"}


@router.get("/feeds/export")
def export_feeds_endpoint(request: Request, format: str = "opml") -> Response:
    """Export all registered feeds as an OPML or markdown document.

    The response is a file download with an appropriate Content-Disposition header.
    OPML format uses media type ``application/xml``; markdown uses ``text/markdown``.

    Args:
        format: ``opml`` (default) or ``markdown``. Any other value returns 422.

    Returns:
        File download response with all currently registered feeds.

    Raises:
        HTTPException 422: When format is not one of the supported values.
    """
    if format not in _SUPPORTED_EXPORT_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported export format '{format}'. Choose from: {sorted(_SUPPORTED_EXPORT_FORMATS)}",
        )

    with Session(request.app.state.engine) as session:
        feeds = list_feeds(session)

    if format == "opml":
        content = build_opml(feeds)
        return Response(
            content=content,
            media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=feeds.opml"},
        )

    # markdown
    content = build_markdown(feeds)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=feeds.md"},
    )
