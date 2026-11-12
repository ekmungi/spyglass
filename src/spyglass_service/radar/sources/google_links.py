"""Replace an item's Google News redirect address with the publisher's own address.

Google News results are stored with a `news.google.com` link that only redirects through a
script, which the reader cannot fetch. The collector resolves the newest few links of each
search; this module resolves one more on demand, just before an item's page is read, using the
same decoder. Calls are spaced out because every decode makes requests to Google.
"""

import logging
import threading
import time
from urllib.parse import urlsplit

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar import netguard
from spyglass_service.radar.sources import news_search
from spyglass_service.radar.sources.news_search import DECODE_INTERVAL, DecodeFn

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_HOST = "news.google.com"
# One decode at a time, at least DECODE_INTERVAL apart, however many digests run in parallel.
_lock = threading.Lock()
_last_call: list[float] = [0.0]


def is_google_link(url: str | None) -> bool:
    """True when `url` is a Google News redirect link."""
    return (urlsplit(url or "").hostname or "").lower() == _GOOGLE_NEWS_HOST


def _decode_throttled(url: str, decode: DecodeFn | None) -> str | None:
    """Decode one link, waiting so that calls are at least DECODE_INTERVAL seconds apart."""
    with _lock:
        wait = DECODE_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            results = (decode or news_search.decode_google_urls)([url])
        finally:
            _last_call[0] = time.monotonic()
    return results[0] if results else None


def resolve_item_url(engine: Engine, item_id: int, *, decode: DecodeFn | None = None) -> bool:
    """If the item's address is a Google News link, replace it with the publisher's address.

    Returns True when the address changed. The old address is kept (and the call returns False)
    when the item is unknown, is not a Google link, the decoder fails or raises, or the result
    is not a public http(s) address.
    """
    with Session(engine) as session:
        item = session.get(Item, item_id)
        link = item.url if item else None
    if not is_google_link(link):
        return False
    try:
        resolved = _decode_throttled(link, decode)
    except Exception:  # noqa: BLE001 -- a decoder failure must never fail the digest
        logger.warning("could not decode the Google link of item %s", item_id, exc_info=True)
        return False
    if not resolved or not netguard.is_public_url(resolved):
        return False
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None or item.url != link:
            return False
        item.url = resolved
        session.add(item)
        session.commit()
    return True
