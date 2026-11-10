"""Tests for the per-domain method cache.

`fetch_cache.py` persists the winning acquire() tier per domain so a repeat fetch of
the same domain can start escalation at the previously-winning tier instead of
retrying every lower rung. These tests exercise the module in isolation (upsert
semantics, domain parsing) against a real (temp-file) SQLite engine via the shared
`engine` fixture in conftest.py -- no network, no acquire()/fetch_fulltext involved.
"""

from sqlmodel import Session, select

from spyglass_service.fetch_cache import domain_of, get_cached_tier, record_winning_tier
from spyglass_service.models import DomainFetchMethod


def test_get_cached_tier_returns_none_when_no_row(engine) -> None:
    """A domain with no cache entry yet returns None (caller falls back to full ladder)."""
    assert get_cached_tier(engine, "example.test") is None


def test_record_then_get_round_trips(engine) -> None:
    """A recorded tier is what a subsequent get returns for that exact domain."""
    record_winning_tier(engine, "blocked.test", "T2")

    assert get_cached_tier(engine, "blocked.test") == "T2"


def test_record_winning_tier_upserts_in_place(engine) -> None:
    """Recording a new tier for an already-cached domain REPLACES the row in place --
    no duplicate rows, and the latest write wins."""
    record_winning_tier(engine, "regress.test", "T2")
    record_winning_tier(engine, "regress.test", "T3")

    assert get_cached_tier(engine, "regress.test") == "T3"
    with Session(engine) as session:
        rows = session.exec(
            select(DomainFetchMethod).where(DomainFetchMethod.domain == "regress.test")
        ).all()
    assert len(rows) == 1


def test_get_cached_tier_is_scoped_to_the_domain(engine) -> None:
    """A cached tier for one domain never leaks into another domain's lookup."""
    record_winning_tier(engine, "a.test", "T1")
    record_winning_tier(engine, "b.test", "T3")

    assert get_cached_tier(engine, "a.test") == "T1"
    assert get_cached_tier(engine, "b.test") == "T3"
    assert get_cached_tier(engine, "c.test") is None


def test_domain_of_extracts_lowercased_netloc() -> None:
    """domain_of parses the netloc out of a full URL and lowercases it (host names are
    case-insensitive; a mixed-case URL must still hit the same cache row)."""
    assert domain_of("https://Example.TEST/some/path?x=1") == "example.test"


def test_domain_of_strips_nothing_but_netloc() -> None:
    """domain_of keeps a port if present (a distinct cache key from the bare host) and
    drops path/query/fragment entirely."""
    assert domain_of("https://example.test:8443/a/b#frag") == "example.test:8443"
