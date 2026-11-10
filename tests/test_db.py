"""Tests for database engine creation and initialization."""

from pathlib import Path

from sqlmodel import Session, select, text

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item


def test_init_db_creates_schema_in_fresh_file(tmp_path: Path) -> None:
    """A fresh database file gets all tables; an item can be stored and read back."""
    engine = create_db_engine(tmp_path / "test.db")
    init_db(engine)
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="x1", title="T", url="https://x.test"))
        session.commit()
    with Session(engine) as session:
        items = session.exec(select(Item)).all()
    assert len(items) == 1
    assert items[0].external_id == "x1"


def test_engine_runs_sqlite_in_wal_mode(tmp_path: Path) -> None:
    """WAL mode is required for service-writer + CLI-reader concurrency."""
    engine = create_db_engine(tmp_path / "test.db")
    init_db(engine)
    with Session(engine) as session:
        mode = session.exec(text("PRAGMA journal_mode")).one()[0]
    assert mode == "wal"


def test_create_db_engine_creates_parent_directory(tmp_path: Path) -> None:
    """First run on a machine: the data dir may not exist yet; the engine creates it."""
    target = tmp_path / "nested" / "dir" / "test.db"
    engine = create_db_engine(target)
    init_db(engine)
    assert target.parent.is_dir()


def test_feedback_columns_exist_after_init(tmp_path: Path) -> None:
    """init_db adds the feedback columns to the card table (in-place migration)."""
    engine = create_db_engine(tmp_path / "test.db")
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(card)")).all()}
    assert {"feedback", "feedback_at"} <= cols


def test_embedding_table_exists_after_init(tmp_path: Path) -> None:
    """init_db creates the embedding table."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    with Session(engine) as session:
        tables = {r[0] for r in session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
    assert "embedding" in tables


def test_card_brief_id_column_added_to_legacy_db(tmp_path: Path) -> None:
    """init_db adds card.brief_id to an existing DB that lacks it (in-place migration)."""
    import sqlite3

    path = tmp_path / "legacy.db"

    # Simulate a legacy DB: a minimal card table without brief_id (create_all leaves an
    # existing table untouched, so only _apply_column_migrations can add the column).
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE card (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, "
        "state VARCHAR NOT NULL, summary VARCHAR NOT NULL)"
    )
    conn.execute("INSERT INTO card (item_id, state, summary) VALUES (1, 'new', 's')")
    conn.commit()
    conn.close()

    # Running init_db on the legacy DB must add the column without data loss.
    engine = create_db_engine(path)
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(card)")).all()}
        rows = session.exec(text("SELECT id, brief_id FROM card")).all()
    assert "brief_id" in cols
    assert rows == [(1, None)]  # existing row survives; new column defaults to NULL


def test_brief_table_exists_after_init(tmp_path: Path) -> None:
    """init_db creates the brief table (new table, covered by create_all)."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    with Session(engine) as session:
        tables = {r[0] for r in session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
    assert "brief" in tables


def test_check_db_integrity_true_for_healthy_db(tmp_path: Path) -> None:
    """A freshly initialised DB passes the integrity check."""
    from spyglass_service.db import check_db_integrity

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    assert check_db_integrity(engine) is True


def test_check_db_integrity_false_for_corrupt_db(tmp_path: Path) -> None:
    """A malformed file fails the integrity check rather than raising."""
    from spyglass_service.db import check_db_integrity

    path = tmp_path / "spy.db"
    path.write_bytes(b"not a sqlite database " * 20)
    engine = create_db_engine(path)
    assert check_db_integrity(engine) is False


# ---------------------------------------------------------------------------
# Feed migration tests
# ---------------------------------------------------------------------------


def test_item_feed_url_column_added_on_pre_existing_db(tmp_path: Path) -> None:
    """init_db adds item.feed_url to an existing DB that was created without it."""
    path = tmp_path / "legacy.db"

    # Simulate a pre-existing DB: create tables then manually drop feed_url from item.
    engine = create_db_engine(path)
    init_db(engine)
    engine.dispose()

    # Rebuild the DB without the feed_url column by recreating via raw SQLite.
    import sqlite3
    conn = sqlite3.connect(str(path))
    # Drop and recreate the item table without feed_url to simulate an older schema.
    conn.execute("ALTER TABLE item RENAME TO item_old")
    conn.execute("""
        CREATE TABLE item (
            id INTEGER PRIMARY KEY,
            source VARCHAR NOT NULL,
            external_id VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            url VARCHAR NOT NULL,
            summary VARCHAR,
            source_tags VARCHAR,
            origin VARCHAR,
            published_at DATETIME,
            fetched_at DATETIME NOT NULL
        )
    """)
    conn.execute("INSERT INTO item SELECT id, source, external_id, title, url, summary, source_tags, origin, published_at, fetched_at FROM item_old")
    conn.execute("DROP TABLE item_old")
    conn.commit()
    conn.close()

    # init_db should add feed_url without error.
    engine2 = create_db_engine(path)
    init_db(engine2)
    with Session(engine2) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(item)")).all()}
    assert "feed_url" in cols


def test_item_feed_url_migration_is_idempotent(tmp_path: Path) -> None:
    """Calling init_db twice on a DB that already has feed_url raises no error."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    # Second call must be a no-op, not an error.
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(item)")).all()}
    assert "feed_url" in cols


def test_feed_table_created_by_init_db(tmp_path: Path) -> None:
    """init_db creates the feed table on a fresh database."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    with Session(engine) as session:
        tables = {r[0] for r in session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
    assert "feed" in tables


def test_relevance_score_column_added(tmp_path: Path) -> None:
    """init_db adds the relevance_score column to the card table."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as s:
        cols = {row[1] for row in s.exec(text("PRAGMA table_info(card)")).all()}
    assert "relevance_score" in cols


def test_brief_publish_day_and_reviewed_columns_added_to_legacy_db(tmp_path: Path) -> None:
    """init_db adds brief.publish_day/reviewed to a legacy DB (in-place migration).

    Simulates a legacy DB: a minimal brief table without the two new
    columns (create_all leaves an existing table untouched, so only
    _apply_column_migrations can add them). Asserts both columns exist afterwards with
    the documented defaults, and that an existing row survives with those defaults.
    """
    import sqlite3

    path = tmp_path / "legacy_brief.db"

    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE brief (id INTEGER PRIMARY KEY, created_at DATETIME NOT NULL, "
        "covers_from DATETIME NOT NULL, covers_until DATETIME NOT NULL, markdown VARCHAR NOT NULL, "
        "item_count INTEGER NOT NULL, low_count INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO brief (created_at, covers_from, covers_until, markdown, item_count, low_count) "
        "VALUES ('2026-07-01T00:00:00', '2026-07-01T00:00:00', '2026-07-02T00:00:00', 'md', 1, 0)"
    )
    conn.commit()
    conn.close()

    engine = create_db_engine(path)
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(brief)")).all()}
        rows = session.exec(text("SELECT id, publish_day, reviewed FROM brief")).all()
    assert {"publish_day", "reviewed"} <= cols
    assert rows == [(1, "", 0)]  # existing row survives; new columns take their documented defaults


def test_brief_publish_day_and_reviewed_migration_is_idempotent(tmp_path: Path) -> None:
    """Calling init_db twice on a DB that already has publish_day/reviewed is a no-op, not an error."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    # Second call must not raise or duplicate the columns.
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(brief)")).all()}
    assert {"publish_day", "reviewed"} <= cols


def test_content_structured_failure_columns_added_to_legacy_db(tmp_path: Path) -> None:
    """init_db adds Content's 4 structured-failure columns to a legacy DB.

    Simulates a legacy DB: a minimal content table without
    detected_type/tier_reached/http_status/error_class (create_all leaves an existing
    table untouched, so only _apply_column_migrations can add them). Asserts all four
    columns exist afterwards and an existing row survives with NULL defaults --
    the DoD live-verify runs this exact migration against a copy of the prod DB.
    """
    import sqlite3

    path = tmp_path / "legacy_content.db"

    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE content (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, "
        "markdown VARCHAR NOT NULL, text_chars INTEGER NOT NULL, source_url VARCHAR, "
        "content_type VARCHAR, status VARCHAR NOT NULL, error VARCHAR, "
        "fetched_at DATETIME NOT NULL)"
    )
    conn.execute(
        "INSERT INTO content (item_id, markdown, text_chars, status, fetched_at) "
        "VALUES (1, 'old body', 8, 'ok', '2026-07-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    engine = create_db_engine(path)
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(content)")).all()}
        rows = session.exec(
            text(
                "SELECT id, detected_type, tier_reached, http_status, error_class FROM content"
            )
        ).all()
    assert {"detected_type", "tier_reached", "http_status", "error_class"} <= cols
    assert rows == [(1, None, None, None, None)]  # existing row survives; new columns default NULL


def test_content_structured_failure_migration_is_idempotent(tmp_path: Path) -> None:
    """Calling init_db twice on a DB that already has the new Content columns is a no-op."""
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    # Second call must not raise or duplicate the columns.
    init_db(engine)
    with Session(engine) as session:
        cols = {row[1] for row in session.exec(text("PRAGMA table_info(content)")).all()}
    assert {"detected_type", "tier_reached", "http_status", "error_class"} <= cols


# ---------------------------------------------------------------------------
# Backfill RSS feed_url from reader.db
# ---------------------------------------------------------------------------


def _make_reader_db(path: Path, entries: list[tuple[str, str]]) -> None:
    """Create a minimal reader.db stub at path with the given (entry_id, feed_url) pairs.

    Args:
        path: Where to write the stub SQLite file.
        entries: List of (entry_id, feed_url) matching reader's entries table shape.
    """
    import sqlite3  # noqa: PLC0415

    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE entries (id TEXT NOT NULL, feed TEXT NOT NULL)")
    conn.executemany("INSERT INTO entries (id, feed) VALUES (?, ?)", entries)
    conn.commit()
    conn.close()


def test_backfill_rss_feed_urls_sets_null_feed_url(tmp_path: Path) -> None:
    """backfill_rss_feed_urls fills feed_url=NULL RSS items via the reader.db join.

    This reproduces the real-world undercounting: items collected before 0.13.0 have
    feed_url=NULL because the collector did not set that field.  The reader.db already
    tracks which entry belongs to which feed (entries.feed), so we can back-fill the
    gap.
    """
    from spyglass_service.db import backfill_rss_feed_urls  # noqa: PLC0415

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)

    feed_url = "https://example.com/feed"
    # Seed two RSS items with NULL feed_url (legacy, pre-0.13.0 shape).
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="entry-1", title="A", url="https://a.com", feed_url=None))
        session.add(Item(source="rss", external_id="entry-2", title="B", url="https://b.com", feed_url=None))
        # A third item with feed_url already set -- must not be altered.
        session.add(Item(source="rss", external_id="entry-3", title="C", url="https://c.com", feed_url=feed_url))
        # A raindrop item -- must not be touched even if external_id matches.
        session.add(Item(source="raindrop", external_id="entry-1", title="D", url="https://d.com", feed_url=None))
        session.commit()

    reader_db = tmp_path / "reader.db"
    _make_reader_db(reader_db, [("entry-1", feed_url), ("entry-2", feed_url)])

    backfill_rss_feed_urls(engine, reader_db)

    with Session(engine) as session:
        all_items = session.exec(select(Item)).all()

    # Index by (source, external_id) since both rss and raindrop share external_id "entry-1".
    by_key = {(i.source, i.external_id): i for i in all_items}

    # RSS items with NULL feed_url got the correct feed_url.
    assert by_key[("rss", "entry-1")].feed_url == feed_url  # source=rss, was NULL
    assert by_key[("rss", "entry-2")].feed_url == feed_url  # source=rss, was NULL
    # Already-set RSS item unchanged.
    assert by_key[("rss", "entry-3")].feed_url == feed_url
    # Raindrop item with same external_id stays NULL (source != rss).
    assert by_key[("raindrop", "entry-1")].feed_url is None


def test_backfill_rss_feed_urls_missing_reader_db_is_noop(tmp_path: Path) -> None:
    """backfill_rss_feed_urls does nothing (no error) when reader.db does not exist yet."""
    from spyglass_service.db import backfill_rss_feed_urls  # noqa: PLC0415

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)

    with Session(engine) as session:
        session.add(Item(source="rss", external_id="e1", title="X", url="https://x.com", feed_url=None))
        session.commit()

    # reader.db does not exist -- must not raise
    backfill_rss_feed_urls(engine, tmp_path / "nonexistent.db")

    with Session(engine) as session:
        items = session.exec(select(Item)).all()
    assert items[0].feed_url is None  # unchanged


def test_backfill_rss_feed_urls_is_idempotent(tmp_path: Path) -> None:
    """Calling backfill_rss_feed_urls twice produces the same result (safe to re-run on startup)."""
    from spyglass_service.db import backfill_rss_feed_urls  # noqa: PLC0415

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)

    feed_url = "https://example.com/rss"
    with Session(engine) as session:
        session.add(Item(source="rss", external_id="e1", title="X", url="https://x.com", feed_url=None))
        session.commit()

    reader_db = tmp_path / "reader.db"
    _make_reader_db(reader_db, [("e1", feed_url)])

    backfill_rss_feed_urls(engine, reader_db)
    backfill_rss_feed_urls(engine, reader_db)  # second call must be a no-op

    with Session(engine) as session:
        items = session.exec(select(Item)).all()
    assert items[0].feed_url == feed_url


def test_item_count_map_includes_backfilled_items(tmp_path: Path) -> None:
    """After backfill, _item_count_map returns the correct count including legacy items.

    This directly tests the Feeds-tab undercounting symptom: before the backfill,
    legacy RSS items with feed_url=NULL are not counted; after the backfill they are.
    """
    from spyglass_service.api_feeds import _item_count_map  # noqa: PLC0415
    from spyglass_service.db import backfill_rss_feed_urls  # noqa: PLC0415
    from spyglass_service.models import Feed  # noqa: PLC0415

    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)

    feed_url = "https://news.example.com/rss"

    with Session(engine) as session:
        session.add(Feed(feed_url=feed_url, name="Example News", kind="rss", added_via="manual", enabled=True))
        # One item collected AFTER 0.13.0: has feed_url set.
        session.add(Item(source="rss", external_id="new-1", title="New", url="https://news.example.com/1", feed_url=feed_url))
        # Two legacy items collected BEFORE 0.13.0: feed_url=NULL, but reader.db knows them.
        session.add(Item(source="rss", external_id="old-1", title="Old1", url="https://news.example.com/2", feed_url=None))
        session.add(Item(source="rss", external_id="old-2", title="Old2", url="https://news.example.com/3", feed_url=None))
        session.commit()

    # Before backfill: count = 1 (only the post-0.13.0 item).
    with Session(engine) as session:
        counts_before = _item_count_map(session)
    assert counts_before.get(feed_url, 0) == 1

    reader_db = tmp_path / "reader.db"
    _make_reader_db(reader_db, [("old-1", feed_url), ("old-2", feed_url)])
    backfill_rss_feed_urls(engine, reader_db)

    # After backfill: count = 3 (all three items attributed to the feed).
    with Session(engine) as session:
        counts_after = _item_count_map(session)
    assert counts_after.get(feed_url, 0) == 3
