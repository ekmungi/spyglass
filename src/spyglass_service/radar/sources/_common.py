"""Helpers shared by the radar collectors: ids, run logging, item lookups and extra data."""

import hashlib
import logging
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Item, RunLog
from spyglass_service.radar import netguard
from spyglass_service.radar.models import ItemExtra, dumps, loads

logger = logging.getLogger(__name__)

# The agent every collector request sends: the one fixed page-fetch agent (no personal detail).
USER_AGENT = netguard.PAGE_USER_AGENT

# Seconds a collector waits for one HTTP response.
HTTP_TIMEOUT = 25.0

# Held while Gmail or Slack is read. The capture poll (every minute by default) and a cycle's collectors both
# read and then rewrite the same "gmail_seen" and "slack_watermark" documents; without this one
# lock, two runs could handle the same messages and the later write could undo the earlier one.
capture_sources_lock = threading.Lock()


class NotConfigured(Exception):
    """Raised by a collector whose credentials or settings are absent: not a failure."""


def short_hash(text: str, length: int = 20) -> str:
    """Stable hex digest of `text`, shortened; used for external ids."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]  # noqa: S324 -- not security


def host_of(url: str) -> str | None:
    """Host name of a URL without a leading "www.", or None when it has none."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def http_get_bytes(url: str, params: dict | None = None) -> bytes:
    """GET a URL and return the body; raises httpx.HTTPError on a failed response.

    Uses the guarded page-fetch client: public addresses only on every redirect hop, read-only,
    no cookies or credential headers, and the generic agent.
    """
    with netguard.page_client(timeout=HTTP_TIMEOUT) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.content


def log_run(
    engine: Engine, source: str, status: str, detail: str | None, started: datetime
) -> None:
    """Write one RunLog row (the Activity feed and the sources endpoint read these).

    Args:
        engine: Database engine.
        source: Collector name, e.g. "radar:news".
        status: "ok", "error" or "skipped".
        detail: A short human sentence; truncated to 500 characters.
        started: When the run began.
    """
    with Session(engine) as session:
        session.add(
            RunLog(
                source=source,
                status=status,
                detail=(detail or "")[:500] or None,
                started_at=started,
                finished_at=datetime.now(UTC),
            )
        )
        session.commit()


def item_ids_by_external(
    engine: Engine, source: str, external_ids: Iterable[str]
) -> dict[str, int]:
    """Map external_id -> item id for the stored items of `source` among `external_ids`."""
    wanted = list(set(external_ids))
    found: dict[str, int] = {}
    with Session(engine) as session:
        # Chunked so a long list never exceeds SQLite's bound-variable limit.
        for start in range(0, len(wanted), 500):
            chunk = wanted[start : start + 500]
            rows = session.exec(
                select(Item.external_id, Item.id)
                .where(Item.source == source)
                .where(Item.external_id.in_(chunk))  # type: ignore[attr-defined]
            ).all()
            found.update({ext: item_id for ext, item_id in rows})
    return found


def merge_extras(engine: Engine, updates: dict[int, dict]) -> int:
    """Merge key/value data into each item's ItemExtra row (created when missing).

    Existing keys not named in `updates` are kept. Returns how many items were touched.
    """
    if not updates:
        return 0
    with Session(engine) as session:
        rows = session.exec(
            select(ItemExtra).where(ItemExtra.item_id.in_(list(updates)))  # type: ignore[attr-defined]
        ).all()
        by_item = {row.item_id: row for row in rows}
        for item_id, data in updates.items():
            row = by_item.get(item_id)
            if row is None:
                session.add(ItemExtra(item_id=item_id, data=dumps(data)))
                continue
            merged = {**(loads(row.data, {}) or {}), **data}
            row.data = dumps(merged)
            session.add(row)
        session.commit()
    return len(updates)
