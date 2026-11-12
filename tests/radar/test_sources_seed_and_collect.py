"""Tests for the seed feed list, the legacy collector wrapper and collect_all."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.feed_registry import NotAFeedError
from spyglass_service.models import Card, Feed, RunLog
from spyglass_service.radar.sources import COLLECTORS, collect_all
from spyglass_service.radar.sources._common import NotConfigured
from spyglass_service.radar.sources.legacy import RecentRssCollector
from spyglass_service.radar.sources.seed_feeds import SEEDS, apply_seed_feeds

from .test_sources_support import all_items, make_engine, make_settings

TWO = (("Alpha", "https://a.example/feed", "x"), ("Beta", "https://b.example/feed", "x"))


def fake_add(session, url, name, scratch):
    """Stands in for the registry: inserts the row the way add_feed does."""
    if "bad" in url:
        raise NotAFeedError(url, reason="not a feed")
    feed = Feed(feed_url=url, name=name, kind="rss", added_via="manual", name_overridden=True)
    session.add(feed)
    session.commit()
    session.refresh(feed)
    return feed


def test_seed_list_has_unique_https_addresses_and_names() -> None:
    urls = [u for _, u, _ in SEEDS]
    assert len(set(urls)) == len(urls) and all(u.startswith("https://") for u in urls)
    assert len({n for n, _, _ in SEEDS}) == len(SEEDS)


def test_apply_seed_feeds_adds_missing_is_idempotent_and_reports_failures(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        seeds = TWO + (("Broken", "https://bad.example/feed", "x"),)
        first = apply_seed_feeds(engine, make_settings(), add=fake_add, seeds=seeds)
        assert first["added"] == ["Alpha", "Beta"]
        assert first["failed"] == [{"name": "Broken", "url": "https://bad.example/feed",
                                    "error": "not a feed"}]
        second = apply_seed_feeds(engine, make_settings(), add=fake_add, seeds=TWO)
        assert second["added"] == [] and second["existing"] == ["Alpha", "Beta"]
        with Session(engine) as session:
            assert {f.added_via for f in session.exec(select(Feed)).all()} == {"seed"}
    finally:
        engine.dispose()


def test_seeding_leaves_feeds_the_user_added_untouched(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        with Session(engine) as session:
            for name, url in [("arXiv general AI", "https://export.arxiv.org/rss/cs.AI"),
                              ("Forbes Innovation", "https://www.forbes.com/innovation/feed/")]:
                session.add(Feed(feed_url=url, name=name, kind="rss", added_via="manual"))
            session.commit()
        result = apply_seed_feeds(engine, make_settings(), add=fake_add, seeds=TWO)
        assert "disabled" not in result
        with Session(engine) as session:
            rows = session.exec(select(Feed)).all()
        assert all(f.enabled for f in rows) and len(rows) == 4
    finally:
        engine.dispose()


def test_recent_collector_drops_old_and_switched_off_entries(monkeypatch, tmp_path) -> None:
    from spyglass_service.collectors.rss import RssCollector

    now = datetime.now(UTC)
    items = [
        CollectedItem("rss", "new", "New", "u1", published_at=now, feed_url="https://on/feed"),
        CollectedItem("rss", "old", "Old", "u2", published_at=now - timedelta(days=90),
                      feed_url="https://on/feed"),
        CollectedItem("rss", "off", "Off", "u3", published_at=now, feed_url="https://off/feed"),
        CollectedItem("rss", "undated", "Undated", "u4", feed_url="https://on/feed"),
        CollectedItem("rss", "naive", "Naive", "u5", published_at=datetime.now(),
                      feed_url="https://on/feed"),
    ]
    monkeypatch.setattr(RssCollector, "collect", lambda self: items)
    base = RssCollector(["https://on/feed"], tmp_path / "r.db")
    kept = RecentRssCollector(base, {"https://on/feed"}, 21).collect()
    assert [i.external_id for i in kept] == ["new", "undated", "naive"]


def runners(**overrides):
    table = {key: (lambda e, s: (1, "1 new")) for key in COLLECTORS}
    table.update(overrides)
    return table


def test_collect_all_isolates_failures_and_logs_each_run(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        def boom(e, s):
            raise RuntimeError("api down")

        def absent(e, s):
            raise NotConfigured("no token")

        counts = collect_all(engine, make_settings(),
                             runners=runners(hn=boom, slack=absent))
        assert counts == {"news": 1, "hn": 0, "hf_papers": 1, "gmail": 1, "slack": 0,
                          "watch": 1, "fda": 1}
        with Session(engine) as session:
            logs = {r.source: r for r in session.exec(select(RunLog)).all()}
        assert logs["radar:hn"].status == "error" and "api down" in logs["radar:hn"].detail
        assert logs["radar:slack"].status == "skipped"
        assert logs["radar:slack"].detail.startswith("not configured")
        assert logs["radar:news"].status == "ok" and logs["radar:news"].finished_at
    finally:
        engine.dispose()


def test_collect_all_default_runners_degrade_without_credentials_or_watch(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path)
    try:
        # Network collectors stubbed; gmail/slack/watch use the real code paths.
        stub = {k: (lambda e, s: (0, "0 new")) for k in ("news", "hn", "hf_papers")}
        from spyglass_service.radar import sources

        monkeypatch.setattr(sources, "_RUNNERS", {**sources._RUNNERS, **stub})
        counts = collect_all(engine, make_settings())
        assert counts["gmail"] == 0 and counts["slack"] == 0
        with Session(engine) as session:
            logs = {r.source: r.status for r in session.exec(select(RunLog)).all()}
        assert logs["radar:gmail"] == "skipped" and logs["radar:slack"] == "skipped"
    finally:
        engine.dispose()


def test_collect_all_creates_cards_for_stored_items(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        from spyglass_service.ingest import store_items

        def store(e, s):
            return store_items(e, [CollectedItem("hn", "1", "T", "https://x.example/")]), "1 new"

        collect_all(engine, make_settings(), runners=runners(hn=store))
        assert len(all_items(engine, "hn")) == 1
        with Session(engine) as session:
            assert len(session.exec(select(Card)).all()) == 1
    finally:
        engine.dispose()
