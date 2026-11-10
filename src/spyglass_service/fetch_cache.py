"""Per-domain acquire() method cache.

Persists the last-known winning tier for a domain (see `models.DomainFetchMethod`) so
`documents.fetch_fulltext` can pass it to `fetch_acquire.acquire()` as `start_tier`,
skipping lower-tier attempts a domain is already known to need. This bounds the
escalation cost of an automatic batch to once per DOMAIN rather than once per URL.

Only the winning tier is stored -- there is no history, no expiry, and no per-URL
granularity. A domain that never needed escalation (won at T0) is never written here
(see `documents.fetch_fulltext`'s record-only-if-above-T0 rule) so easy domains keep
starting cheap every time.
"""

from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import Engine
from sqlmodel import Session, select

from .models import DomainFetchMethod


def domain_of(url: str) -> str:
    """The lowercased netloc (host, plus port if present) of `url`.

    Host names are case-insensitive but a cache row is a plain string key, so this
    normalizes case before it ever reaches the table -- otherwise "Example.test" and
    "example.test" would silently miss each other's cached tier. Path/query/fragment
    are dropped entirely: the cache is domain-scoped, not URL-scoped.
    """
    return urlparse(url).netloc.lower()


def get_cached_tier(engine: Engine, domain: str) -> str | None:
    """The winning tier last recorded for `domain`, or None if never recorded.

    None is also the correct return for a domain that has only ever won at T0 (see
    `record_winning_tier`'s above-T0 rule) -- from the caller's point of view "no
    cache entry" and "always wins at T0" both mean "start the ladder at T0".
    """
    with Session(engine) as session:
        row = session.exec(
            select(DomainFetchMethod).where(DomainFetchMethod.domain == domain)
        ).first()
    return row.tier if row else None


def record_winning_tier(engine: Engine, domain: str, tier: str) -> None:
    """Upsert `domain`'s cached tier to `tier`, replacing any prior value in place.

    One row per domain (DomainFetchMethod.domain is unique) -- an existing row is
    updated (tier + updated_at) rather than a second row being inserted, so a
    regression (a domain that used to win at T2 now needing T3) simply overwrites the
    old value instead of accumulating history this cache doesn't need.
    """
    with Session(engine) as session:
        row = session.exec(
            select(DomainFetchMethod).where(DomainFetchMethod.domain == domain)
        ).first()
        if row is None:
            session.add(DomainFetchMethod(domain=domain, tier=tier))
        else:
            row.tier = tier
            row.updated_at = datetime.now(UTC)
            session.add(row)
        session.commit()
