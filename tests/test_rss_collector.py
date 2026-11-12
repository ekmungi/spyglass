"""Tests for the RSS collector built on the reader library (local fixture, no network)."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import httpx
from sqlmodel import Session, select

from spyglass_service.collectors.rss import RssCollector, _strip_html, resolve_feed_url, write_feed_health
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def make_collector(tmp_path: Path, web: str) -> RssCollector:
    """Collector subscribed to the fixture feed served at `web`, storing reader state in tmp."""
    return RssCollector(feed_urls=[f"{web}/{FIXTURE.name}"], reader_db_path=tmp_path / "reader.db")


def test_collects_entries_from_a_feed(tmp_path: Path, fixtures_web_url: str) -> None:
    """Both fixture entries come back as collected items with source 'rss'."""
    items = make_collector(tmp_path, fixtures_web_url).collect()
    assert len(items) == 2
    assert {i.source for i in items} == {"rss"}
    titles = {i.title for i in items}
    assert "EU AI Act implementation timeline moves" in titles


def test_entries_carry_stable_external_ids_and_urls(tmp_path: Path, fixtures_web_url: str) -> None:
    """External ids come from the feed guid so re-fetches dedupe correctly."""
    items = make_collector(tmp_path, fixtures_web_url).collect()
    by_id = {i.external_id: i for i in items}
    assert "https://example.test/posts/1" in by_id
    assert by_id["https://example.test/posts/1"].url == "https://example.test/posts/1"


def test_entries_carry_the_feed_title_as_origin(tmp_path: Path, fixtures_web_url: str) -> None:
    """Each item records WHICH feed it came from, not just the collector name."""
    items = make_collector(tmp_path, fixtures_web_url).collect()
    assert {i.origin for i in items} == {"Sample Research Feed"}


def test_recollect_is_idempotent(tmp_path: Path, fixtures_web_url: str) -> None:
    """Collecting twice from an unchanged feed yields the same item set, no errors."""
    collector = make_collector(tmp_path, fixtures_web_url)
    first = collector.collect()
    second = collector.collect()
    assert {i.external_id for i in first} == {i.external_id for i in second}


def test_strip_html_cleans_feed_summaries() -> None:
    """RSS descriptions embed markup; the collector stores clean plain text."""
    assert _strip_html('<p>A <img src="x"/> caption</p>') == "A caption"
    assert _strip_html(None) is None
    assert _strip_html("<br/>") is None


def test_youtube_channel_id_url_rewrites_to_the_rss_feed() -> None:
    """A /channel/UC... url is a page, not a feed; rewrite it directly (no network)."""
    url = "https://www.youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA"
    assert resolve_feed_url(url) == (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCHnyfMqiRRG1u-2MsSQLbXA"
    )


def test_youtube_handle_url_resolves_via_the_channel_page() -> None:
    """An @handle url needs the page once to learn the channel id."""
    page = '<html>..."channelId":"UCabc123XYZ_-45678901234"...</html>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page, headers={"content-type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert resolve_feed_url("https://www.youtube.com/@NVIDIA", client=client) == (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123XYZ_-45678901234"
    )


def test_unresolvable_youtube_handle_keeps_the_original_url() -> None:
    """Resolution is best-effort: failures fall back to the url as written."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url = "https://www.youtube.com/@Unknown"
    assert resolve_feed_url(url, client=client) == url


def test_non_youtube_urls_pass_through_untouched() -> None:
    assert resolve_feed_url("https://example.test/feed.xml") == "https://example.test/feed.xml"


def test_unreachable_feed_does_not_raise(tmp_path: Path) -> None:
    """A broken feed yields zero items instead of crashing the run (partial failure)."""
    collector = RssCollector(
        feed_urls=[str(tmp_path / "missing.xml")], reader_db_path=tmp_path / "reader.db"
    )
    assert collector.collect() == []


def test_collected_items_carry_the_feed_url(tmp_path: Path, fixtures_web_url: str) -> None:
    """Each RSS item carries feed_url equal to the resolved feed key.

    feed_url on CollectedItem is Point 2 of the 3-point threading chain;
    this test verifies the RssCollector sets it correctly from entry.feed.url.
    """
    items = make_collector(tmp_path, fixtures_web_url).collect()
    assert len(items) > 0
    fixture_url = f"{fixtures_web_url}/{FIXTURE.name}"
    for item in items:
        assert item.feed_url == fixture_url, (
            f"Expected feed_url={fixture_url!r}, got {item.feed_url!r}"
        )


def test_feed_url_stored_in_db_via_ingest(tmp_path: Path, fixtures_web_url: str) -> None:
    """RSS item's feed_url survives the collect -> ingest -> db round-trip (Point 3).

    This integration test verifies all 3 points together: CollectedItem.feed_url
    set by RssCollector._to_item, and mapped through store_items into Item.feed_url.
    A non-RSS item (source='fake') keeps feed_url=None (Raindrop / other sources
    are unaffected by the threading change).
    """
    from sqlmodel import Session, SQLModel, create_engine, select

    from spyglass_service.collectors.base import CollectedItem
    from spyglass_service.ingest import store_items
    from spyglass_service.models import Item

    db_path = tmp_path / "ingest_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    # Collect from the fixture feed.
    rss_items = make_collector(tmp_path, fixtures_web_url).collect()

    # Also construct a non-RSS item (no feed_url expected).
    non_rss = CollectedItem(
        source="fake",
        external_id="non-rss-1",
        title="Non-RSS item",
        url="https://example.test/non-rss",
        summary=None,
        published_at=None,
    )

    store_items(engine, rss_items + [non_rss])

    with Session(engine) as session:
        stored = session.exec(select(Item)).all()

    rss_stored = [i for i in stored if i.source == "rss"]
    non_rss_stored = [i for i in stored if i.source == "fake"]

    fixture_url = f"{fixtures_web_url}/{FIXTURE.name}"
    assert len(rss_stored) > 0
    for item in rss_stored:
        assert item.feed_url == fixture_url, (
            f"Expected feed_url={fixture_url!r}, got {item.feed_url!r}"
        )

    assert len(non_rss_stored) == 1
    assert non_rss_stored[0].feed_url is None


# ---------------------------------------------------------------------------
# write_feed_health tests
# ---------------------------------------------------------------------------


def _make_engine_with_feeds(tmp_path: Path, feed_urls: list[str]):
    """Create a fresh engine with the given Feed rows pre-populated."""
    engine = create_db_engine(tmp_path / "spyglass.db")
    init_db(engine)
    with Session(engine) as session:
        for url in feed_urls:
            session.add(Feed(feed_url=url, name="Test Feed", kind="rss", added_via="manual"))
        session.commit()
    return engine


def _make_fake_reader(feeds: list[MagicMock]) -> MagicMock:
    """Return a fake reader context manager whose get_feeds() returns feeds."""
    fake_reader = MagicMock()
    fake_reader.get_feeds.return_value = feeds
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=fake_reader)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_feed_mock(url: str, *, ok: bool, ts: datetime | None = None) -> MagicMock:
    """Build a mock reader Feed with controlled last_exception / last_updated."""
    f = MagicMock()
    f.url = url
    if ok:
        f.last_exception = None
        f.last_updated = ts or datetime.now(UTC)
    else:
        exc_info = MagicMock()
        exc_info.type_name = "reader.exceptions.ParseError"
        exc_info.value_str = "Invalid XML"
        f.last_exception = exc_info
        f.last_updated = None
    return f


def test_write_feed_health_sets_ok_on_successful_feed(tmp_path: Path, monkeypatch) -> None:
    """A feed with no last_exception gets status='ok', last_fetch_at set, last_error=None."""
    feed_url = "https://example.test/feed.xml"
    engine = _make_engine_with_feeds(tmp_path, [feed_url])
    ts = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)
    fake_feed = _make_feed_mock(feed_url, ok=True, ts=ts)
    fake_ctx = _make_fake_reader([fake_feed])

    from spyglass_service.collectors import rss as rss_mod
    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == feed_url)).one()

    assert row.last_fetch_status == "ok"
    # SQLite stores datetimes without timezone; compare the naive UTC values.
    assert row.last_fetch_at is not None
    stored = row.last_fetch_at.replace(tzinfo=None) if row.last_fetch_at.tzinfo else row.last_fetch_at
    expected = ts.replace(tzinfo=None)
    assert stored == expected
    assert row.last_error is None


def test_write_feed_health_sets_error_on_failed_feed(tmp_path: Path, monkeypatch) -> None:
    """A feed with last_exception gets status='error' and a truncated reason string."""
    feed_url = "https://example.test/broken.xml"
    engine = _make_engine_with_feeds(tmp_path, [feed_url])
    fake_feed = _make_feed_mock(feed_url, ok=False)
    fake_ctx = _make_fake_reader([fake_feed])

    from spyglass_service.collectors import rss as rss_mod
    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == feed_url)).one()

    assert row.last_fetch_status == "error"
    assert row.last_error is not None
    assert "ParseError" in row.last_error
    assert "Invalid XML" in row.last_error
    assert len(row.last_error) <= 500


def test_write_feed_health_truncates_long_error(tmp_path: Path, monkeypatch) -> None:
    """An exception with a huge message is capped at 500 chars in last_error."""
    feed_url = "https://example.test/verbose.xml"
    engine = _make_engine_with_feeds(tmp_path, [feed_url])

    exc_info = MagicMock()
    exc_info.type_name = "builtins.RuntimeError"
    exc_info.value_str = "x" * 1000
    fake_feed = MagicMock()
    fake_feed.url = feed_url
    fake_feed.last_exception = exc_info
    fake_feed.last_updated = None
    fake_ctx = _make_fake_reader([fake_feed])

    from spyglass_service.collectors import rss as rss_mod
    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == feed_url)).one()

    assert row.last_error is not None
    assert len(row.last_error) <= 500


def test_write_feed_health_skips_reader_feed_with_no_registry_match(
    tmp_path: Path, monkeypatch
) -> None:
    """A feed known to reader but absent from the Feed registry is silently skipped."""
    registered_url = "https://example.test/registered.xml"
    unknown_url = "https://example.test/unknown.xml"
    engine = _make_engine_with_feeds(tmp_path, [registered_url])

    fake_feeds = [
        _make_feed_mock(registered_url, ok=True),
        _make_feed_mock(unknown_url, ok=True),  # not in registry
    ]
    fake_ctx = _make_fake_reader(fake_feeds)

    from spyglass_service.collectors import rss as rss_mod
    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        all_feeds = session.exec(select(Feed)).all()

    assert len(all_feeds) == 1  # no new row created
    assert all_feeds[0].feed_url == registered_url
    assert all_feeds[0].last_fetch_status == "ok"


def test_write_feed_health_bad_feed_does_not_block_good_feed(
    tmp_path: Path, monkeypatch
) -> None:
    """One feed that fails the DB write must not abort writing the others."""
    good_url = "https://example.test/good.xml"
    bad_url = "https://example.test/bad.xml"
    engine = _make_engine_with_feeds(tmp_path, [good_url, bad_url])
    ts = datetime(2026, 6, 29, 10, 0, 0, tzinfo=UTC)

    exc_info = MagicMock()
    exc_info.type_name = "reader.exceptions.ParseError"
    exc_info.value_str = "bad xml"

    bad_feed = MagicMock()
    bad_feed.url = bad_url
    bad_feed.last_exception = exc_info
    bad_feed.last_updated = None

    fake_feeds = [
        _make_feed_mock(good_url, ok=True, ts=ts),
        bad_feed,
    ]
    fake_ctx = _make_fake_reader(fake_feeds)

    from spyglass_service.collectors import rss as rss_mod
    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        good_row = session.exec(select(Feed).where(Feed.feed_url == good_url)).one()
        bad_row = session.exec(select(Feed).where(Feed.feed_url == bad_url)).one()

    assert good_row.last_fetch_status == "ok"
    assert bad_row.last_fetch_status == "error"


def test_write_feed_health_isolates_write_exception(
    tmp_path: Path, monkeypatch
) -> None:
    """_write_one_feed_health raising for feed-1 must not abort writing feed-2.

    Scenario: two feeds are registered and both appear in reader output.
    The helper raises RuntimeError for the first feed's url.  The except
    Exception guard in write_feed_health must catch that raise and continue
    the loop, so the second feed's row still gets status='ok'.

    Confirmation: if the except block is removed from write_feed_health the
    RuntimeError propagates and the second feed's row is never written, which
    makes the assertion on feed-2 fail.
    """
    url1 = "https://example.test/exploding.xml"
    url2 = "https://example.test/surviving.xml"
    engine = _make_engine_with_feeds(tmp_path, [url1, url2])
    ts = datetime(2026, 6, 29, 11, 0, 0, tzinfo=UTC)

    fake_feeds = [
        _make_feed_mock(url1, ok=True, ts=ts),
        _make_feed_mock(url2, ok=True, ts=ts),
    ]
    fake_ctx = _make_fake_reader(fake_feeds)

    from spyglass_service.collectors import rss as rss_mod

    monkeypatch.setattr(rss_mod, "make_reader", lambda *a, **kw: fake_ctx)

    # Import the real helper so we can delegate to it for url2.
    real_write_one = rss_mod._write_one_feed_health

    def _patched_write_one(engine_arg: object, reader_feed: object, now: object) -> None:
        """Raise for url1; delegate to the real implementation for all other feeds."""
        if getattr(reader_feed, "url", None) == url1:
            raise RuntimeError("boom — simulated DB write failure")
        real_write_one(engine_arg, reader_feed, now)  # type: ignore[arg-type]

    monkeypatch.setattr(rss_mod, "_write_one_feed_health", _patched_write_one)

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row1 = session.exec(select(Feed).where(Feed.feed_url == url1)).one()
        row2 = session.exec(select(Feed).where(Feed.feed_url == url2)).one()

    # url2 must have been written despite the exception raised for url1.
    assert row2.last_fetch_status == "ok", (
        "feed-2 status not set — the except guard failed to isolate feed-1's exception"
    )
    # url1 was never written (the raise aborted that iteration before any DB update).
    assert row1.last_fetch_status is None, (
        "feed-1 should have no status written — the raise happened before the DB update"
    )


def test_write_feed_health_real_fixture_good_feed(tmp_path: Path, fixtures_web_url: str) -> None:
    """Integration: writing health against a real reader DB with the fixture feed."""
    engine = _make_engine_with_feeds(tmp_path, [f"{fixtures_web_url}/{FIXTURE.name}"])

    # First populate the reader DB via a real collect().
    collector = RssCollector(
        feed_urls=[f"{fixtures_web_url}/{FIXTURE.name}"], reader_db_path=tmp_path / "reader.db"
    )
    collector.collect()

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == f"{fixtures_web_url}/{FIXTURE.name}")).one()

    assert row.last_fetch_status == "ok"
    assert row.last_fetch_at is not None
    assert row.last_error is None


def test_write_feed_health_real_fixture_broken_feed(tmp_path: Path, fixtures_web_url: str) -> None:
    """Integration: a non-feed file produces status='error' via the real reader."""
    not_a_feed = f"{fixtures_web_url}/not_a_feed.txt"
    engine = _make_engine_with_feeds(tmp_path, [not_a_feed])

    collector = RssCollector(
        feed_urls=[not_a_feed], reader_db_path=tmp_path / "reader.db"
    )
    collector.collect()  # does not raise; reader records the error internally

    write_feed_health(engine, tmp_path / "reader.db")

    with Session(engine) as session:
        row = session.exec(select(Feed).where(Feed.feed_url == not_a_feed)).one()

    assert row.last_fetch_status == "error"
    assert row.last_error is not None
    assert len(row.last_error) <= 500
