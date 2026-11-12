"""RSS/Atom collector built on the reader library (storage, dedupe, conditional GET)."""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from reader import FeedExistsError, make_reader
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.feed_http import is_web_feed_address, use_browser_user_agent
from spyglass_service.models import Feed
from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

# Maximum characters stored in Feed.last_error (prevents huge tracebacks bloating the DB).
_MAX_ERROR_LEN = 500

# RSS descriptions often embed HTML; cards want clean text.
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")

# YouTube channel PAGES are not feeds; their RSS lives at feeds/videos.xml.
_YT_CHANNEL = re.compile(r"^https?://(?:www\.)?youtube\.com/channel/(UC[\w-]+)")
_YT_HANDLE = re.compile(r"^https?://(?:www\.)?youtube\.com/@[\w.-]+/?$")
# The id appears as "channelId":"UC..." or inside the embedded RSS link
# (channel_id=UC...); pages vary, so try both.
_YT_CHANNEL_ID = re.compile(r'(?:"channelId"\s*:\s*"|channel_id=)(UC[\w-]+)')
_YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
# The guarded client sends no cookies, so the consent cookie that skips YouTube's EU interstitial
# is no longer sent; where that page replaces the channel page the handle cannot be resolved.
_YT_HEADERS = {"Accept-Language": "en"}


def resolve_feed_url(url: str, client: httpx.Client | None = None) -> str:
    """Turn known non-feed urls into their real feed urls (best-effort).

    YouTube /channel/UC... rewrites directly; /@handle pages are fetched once to
    learn the channel id. Anything unresolvable returns the url as written so a
    typo degrades to the reader's per-feed error, never a crash.
    """
    channel = _YT_CHANNEL.match(url)
    if channel:
        return _YT_FEED.format(channel.group(1))
    if _YT_HANDLE.match(url):
        owns_client = client is None
        client = client or netguard.page_client(timeout=20)
        try:
            response = client.get(url, headers=_YT_HEADERS)
            if response.status_code == 200:
                found = _YT_CHANNEL_ID.search(response.text)
                if found:
                    return _YT_FEED.format(found.group(1))
        except httpx.HTTPError:
            pass
        finally:
            if owns_client:
                client.close()
    return url


def _strip_html(text: str | None) -> str | None:
    """Remove HTML tags and collapse whitespace from a feed summary."""
    if not text:
        return None
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip() or None


class RssCollector:
    """Collects entries from the subscribed feeds via a reader-managed database.

    reader handles fetching, parsing, and conditional requests; this class only
    subscribes the configured URLs and maps entries to CollectedItem.
    Only web addresses are read: the reader is made without a feed root (which switches local
    feeds off), and a stored address that is a file path is skipped with a log line.
    """

    name = "rss"

    def __init__(self, feed_urls: list[str], reader_db_path: Path) -> None:
        self._feed_urls = feed_urls
        self._db_path = reader_db_path

    def collect(self) -> list[CollectedItem]:
        """Subscribe any new URLs, refresh all feeds, and return current entries.

        Individual feed failures are reader-internal (logged per feed) and never
        raise here: a broken feed must not block the rest of the morning.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with make_reader(str(self._db_path)) as reader:
            use_browser_user_agent(reader)  # for sites that block unknown clients
            for url in self._feed_urls:
                if not is_web_feed_address(url):
                    logger.warning("feed skipped: %r is not a web address", url[:200])
                    continue
                try:
                    reader.add_feed(resolve_feed_url(url))
                except FeedExistsError:
                    pass
            reader.update_feeds(workers=1)
            return [self._to_item(entry) for entry in reader.get_entries()]

    @staticmethod
    def _to_item(entry) -> CollectedItem:
        """Map a reader entry to the normalized collected-item shape."""
        published: datetime | None = entry.published or entry.updated
        # The feed's own title tells the user WHICH publication this is;
        # the feed URL is the durable registry join key (Feed.feed_url == Item.feed_url).
        feed = getattr(entry, "feed", None)
        origin = getattr(feed, "title", None) if feed else None
        feed_url = getattr(feed, "url", None) if feed else None
        return CollectedItem(
            source="rss",
            external_id=entry.id,
            title=entry.title or entry.link or entry.id,
            url=entry.link or entry.id,
            summary=_strip_html(entry.summary),
            published_at=published,
            origin=origin,
            feed_url=feed_url,
        )


def write_feed_health(engine: Engine, reader_db_path: Path) -> None:
    """Write per-feed fetch outcomes from the reader DB onto matching Feed registry rows.

    Opens the reader DB at reader_db_path (read-only pass — reader persists state across
    open/close), iterates every feed it knows about, and for each one finds the matching
    Feed row by feed_url == feed.url.  On match, sets:
      - last_fetch_status: "ok" when last_exception is None, else "error"
      - last_fetch_at:     feed.last_updated (datetime of last successful update), or None
      - last_error:        "<type_name>: <value_str>" truncated to _MAX_ERROR_LEN, or None
      - updated_at:        bumped to now(UTC)

    Feeds absent from the registry are silently skipped (this function never creates rows).
    A per-feed failure during the DB write is logged and skipped so one bad feed never
    blocks the others.

    Args:
        engine:          SQLAlchemy engine connected to the Spyglass database.
        reader_db_path:  Path to the reader SQLite database (must already exist or reader
                         will create an empty one, yielding zero feeds — harmless).
    """
    now = datetime.now(UTC)
    with make_reader(str(reader_db_path)) as reader:
        reader_feeds = list(reader.get_feeds())

    for rf in reader_feeds:
        try:
            _write_one_feed_health(engine, rf, now)
        except Exception:  # noqa: BLE001 -- one bad feed must not abort the others
            logger.exception("Failed to write health for feed %r", getattr(rf, "url", "<unknown>"))


def _write_one_feed_health(engine: Engine, reader_feed, now: datetime) -> None:
    """Update a single Feed row from a reader feed object; skip if no registry match.

    Args:
        engine:       Spyglass DB engine.
        reader_feed:  A reader Feed object with .url, .last_exception, .last_updated.
        now:          UTC timestamp to stamp updated_at with.
    """
    url: str = reader_feed.url

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == url)).first()
        if row is None:
            return  # Not in registry; do not create rows here.

        exc_info = reader_feed.last_exception
        if exc_info is None:
            # Successful update: record ok + the reader's last-updated timestamp.
            row.last_fetch_status = "ok"
            row.last_fetch_at = reader_feed.last_updated
            row.last_error = None
        else:
            # Failed update: store a short human-readable reason, never the full traceback.
            reason = f"{exc_info.type_name}: {exc_info.value_str}"
            row.last_fetch_status = "error"
            row.last_error = reason[:_MAX_ERROR_LEN]
        row.updated_at = now
        session.add(row)
        session.commit()
