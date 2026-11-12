"""Feed registry: pure CRUD helpers over a SQLModel Session (no FastAPI, no HTTP handlers).

Resolution at add-time invariant: add_feed resolves the URL once and stores the RESOLVED URL
as feed_url so that the registry key == the reader key for all downstream tasks.
"""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlmodel import Session, select

from spyglass_service.collectors.feedlist import parse_feed_list
from spyglass_service.collectors.rss import resolve_feed_url
from spyglass_service.config import Settings
from spyglass_service.feed_http import (
    REASONS,
    classify_feed_error,
    is_web_feed_address,
    use_browser_user_agent,
)
from spyglass_service.models import Feed

# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class NotAFeedError(Exception):
    """Raised by add_feed when the resolved URL does not parse as a valid feed.

    Carries the offending URL so the HTTP layer can forward it in the 422 body.
    """

    def __init__(self, url: str, kind: str = "not_a_feed", reason: str | None = None) -> None:
        """Initialise with the URL that failed validation.

        Args:
            url: The resolved URL that could not be parsed as a feed.
            kind: Why: "not_a_feed", "blocked" (the site refused), "unreachable" or "local_file"
                (a path or `file:` address; feeds are read from the web only).
            reason: A plain sentence for the user; defaults to the kind's general reason.
        """
        super().__init__(f"URL is not a parseable feed: {url}")
        self.url = url
        self.kind = kind
        self.reason = reason or REASONS.get(kind, REASONS["not_a_feed"])


# ---------------------------------------------------------------------------
# Internal validation helper
# ---------------------------------------------------------------------------

# YouTube feeds/videos.xml pattern — used to classify kind at insert time.
_YT_FEED_PATH = "feeds/videos.xml"


def _validate_feed(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
    """Attempt to parse resolved_url as an RSS/Atom feed via a throwaway reader instance.

    Uses the reader library (already a project dependency) to add and immediately
    fetch the URL in a temp DB. If reader can parse the feed and the feed object
    has a non-None title, the feed is valid. Otherwise NotAFeedError is raised.

    Choice rationale: reader is already used for collection and handles all
    feed format variants (RSS 1/2, Atom, JSON Feed). Using it here guarantees
    identical acceptance criteria to the live collector, with no extra dependency.
    Local files are never read: a path or a `file:` address is refused before the reader is made,
    and the reader itself is made without a feed root, which switches local feeds off.

    Args:
        resolved_url: The URL after resolve_feed_url() has been applied.
        reader_db_path: Writable path for the throwaway reader DB (caller supplies
            a tmp path so the registry's real DB is never touched).

    Returns:
        (title, kind) where title is the feed's title (or host fallback) and
        kind is one of 'youtube', 'rss'.

    Raises:
        NotAFeedError: If the URL cannot be parsed as a valid feed.
    """
    from reader import ReaderError, make_reader  # local import avoids circular risk

    if not is_web_feed_address(resolved_url):
        raise NotAFeedError(resolved_url, "local_file")
    reader_db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # No feed_root: the library then opens web feeds only, never a file on this computer.
        with make_reader(str(reader_db_path)) as reader:
            use_browser_user_agent(reader)  # the same agent as page fetching
            reader.add_feed(resolved_url)
            reader.update_feeds(workers=1)
            feed_obj = reader.get_feed(resolved_url)
            # reader swallows per-feed parse errors internally; detect them via
            # last_exception being set on the feed object rather than a raised exception.
            failure = getattr(feed_obj, "last_exception", None)
            if failure is not None:
                detail = f"{getattr(failure, 'value_str', '')}\n{getattr(failure, 'traceback_str', '')}"
                kind, reason = classify_feed_error(detail)
                raise NotAFeedError(resolved_url, kind, reason)
            title: str | None = getattr(feed_obj, "title", None)
    except NotAFeedError:
        raise
    except (ReaderError, OSError) as exc:
        raise NotAFeedError(resolved_url) from exc

    if not title:
        # Feed parsed but had no title -- treat as valid with a host fallback.
        title = _host_from_url(resolved_url)

    kind = "youtube" if _YT_FEED_PATH in resolved_url else "rss"
    return title, kind


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------


def _host_from_url(url: str) -> str:
    """Return the hostname of url, or the full url string if parsing fails.

    Args:
        url: Any URL string.

    Returns:
        Hostname component, or the full url on parse failure.
    """
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Public CRUD helpers
# ---------------------------------------------------------------------------


def list_feeds(session: Session) -> list[Feed]:
    """Return all Feed rows, ordered by name then id.

    Args:
        session: Active SQLModel session.

    Returns:
        List of Feed instances (may be empty).
    """
    return list(session.exec(select(Feed).order_by(Feed.name, Feed.id)).all())


def get_feed(session: Session, feed_id: int) -> Feed | None:
    """Return the Feed with the given primary key, or None if absent.

    Args:
        session: Active SQLModel session.
        feed_id: Primary key of the feed row.

    Returns:
        Feed instance or None.
    """
    return session.get(Feed, feed_id)


def add_feed(
    session: Session,
    url: str,
    *,
    name: str | None = None,
    reader_db_path: Path | None = None,
) -> Feed:
    """Resolve, validate, and insert a new feed; dedupes on the resolved URL.

    Steps:
    1. resolve_feed_url(url) -> resolved (YouTube channel -> feeds/videos.xml, etc.)
    2. _validate_feed(resolved) -- raises NotAFeedError if not parseable.
    3. If a Feed row already exists for that resolved URL, return it unchanged (no
       duplicate insert and no rename -- only a fresh insert honours the provided name).
    4. Insert the row.  When a non-empty name is provided, store it and set
       name_overridden=True; otherwise derive the name from the feed title with
       name_overridden=False.

    Args:
        session: Active SQLModel session.
        url: User-supplied feed URL (may need resolution).
        name: Optional friendly display name supplied by the caller.  When non-empty,
            the stored name is exactly this value and name_overridden is set to True so
            that periodic title re-resolution does not clobber it.  When None or empty,
            the name is derived from the feed's own title element (existing behaviour).
        reader_db_path: Optional path for the throwaway validation reader DB.
            Defaults to a system-temp path; tests should pass a tmp_path value.

    Returns:
        The existing or newly created Feed row.

    Raises:
        NotAFeedError: If the resolved URL does not parse as a valid feed.
    """
    if not is_web_feed_address(url):
        raise NotAFeedError(url, "local_file")
    resolved = resolve_feed_url(url)

    # Dedupe: if the resolved URL already exists, return it without re-validating or
    # renaming.  A re-add must never silently rename an already-registered feed.
    existing = session.exec(select(Feed).where(Feed.feed_url == resolved)).first()
    if existing is not None:
        return existing

    # Validation path: use a throwaway reader DB.
    if reader_db_path is None:
        import tempfile  # noqa: PLC0415

        reader_db_path = Path(tempfile.mkdtemp()) / "validate_reader.db"

    title, kind = _validate_feed(resolved, reader_db_path)

    # Honour caller-supplied name on a fresh insert; fall back to feed title.
    caller_name = name.strip() if name else ""
    display_name = caller_name if caller_name else title
    name_overridden = bool(caller_name)

    feed = Feed(
        feed_url=resolved,
        name=display_name,
        kind=kind,
        added_via="manual",
        enabled=True,
        name_overridden=name_overridden,
    )
    session.add(feed)
    session.commit()
    session.refresh(feed)
    return feed


def update_feed(
    session: Session,
    feed_id: int,
    *,
    enabled: bool | None = None,
    name: str | None = None,
) -> Feed | None:
    """Apply partial updates to a feed row; bump updated_at.

    Providing name also sets name_overridden=True so periodic title re-resolution
    does not clobber the user's custom label.

    Args:
        session: Active SQLModel session.
        feed_id: Primary key of the feed to update.
        enabled: If provided, sets the enabled flag.
        name: If provided, sets the display name and marks name_overridden=True.

    Returns:
        The updated Feed row, or None if feed_id does not exist.
    """
    feed = session.get(Feed, feed_id)
    if feed is None:
        return None

    if enabled is not None:
        feed.enabled = enabled
    if name is not None:
        feed.name = name
        feed.name_overridden = True
    feed.updated_at = datetime.now(UTC)

    session.add(feed)
    session.commit()
    session.refresh(feed)
    return feed


def delete_feed(session: Session, feed_id: int) -> bool:
    """Delete the Feed row identified by feed_id.

    Item/card purge and reader tombstones are the responsibility of the
    DELETE endpoint; this function removes ONLY the Feed row.

    Args:
        session: Active SQLModel session.
        feed_id: Primary key of the feed to delete.

    Returns:
        True if a row was deleted, False if feed_id did not exist.
    """
    feed = session.get(Feed, feed_id)
    if feed is None:
        return False
    session.delete(feed)
    session.commit()
    return True


def seed_from_note(settings: Settings, session: Session) -> int:
    """Populate the feed registry from a markdown note if the registry is empty.

    Idempotent: if any Feed rows exist, returns 0 immediately (never reseeds).
    No network validation is performed during seeding -- the URL is resolved
    (YouTube rewrite only; pure-local), inserted with a provisional name equal
    to the URL's hostname, and marked added_via='import'. Real titles are filled
    in by the health write-back after the first live fetch.

    Args:
        settings: Settings instance providing feed_note_path.
        session: Active SQLModel session.

    Returns:
        Number of Feed rows inserted (0 if registry was non-empty or no note).
    """
    # Guard: never reseed a non-empty registry.
    if list_feeds(session):
        return 0

    note_path = settings.feed_note_path
    if note_path is None or not note_path.is_file():
        return 0

    text = note_path.read_text(encoding="utf-8")
    urls = parse_feed_list(text)

    inserted = 0
    seen_resolved: set[str] = set()

    for raw_url in urls:
        resolved = resolve_feed_url(raw_url)
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)

        # Provisional name: hostname of the resolved URL.
        provisional_name = _host_from_url(resolved)

        feed = Feed(
            feed_url=resolved,
            name=provisional_name,
            kind="youtube" if _YT_FEED_PATH in resolved else "rss",
            added_via="import",
            enabled=True,
        )
        session.add(feed)
        inserted += 1

    if inserted:
        session.commit()

    return inserted
