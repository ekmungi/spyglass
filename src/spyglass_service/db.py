"""Database engine setup: SQLite in WAL mode with a sensible busy timeout."""

import logging
import sqlite3
from pathlib import Path

from sqlalchemy import Engine, event, text
from sqlmodel import Session, SQLModel, create_engine

logger = logging.getLogger(__name__)

# Columns added after the first schema shipped: (table, column, SQL type + default).
# Applied idempotently on startup so an existing operational DB upgrades in place.
_ADDED_COLUMNS = [
    ("card", "curated", "BOOLEAN NOT NULL DEFAULT 0"),
    ("card", "category", "VARCHAR"),
    ("card", "group_label", "VARCHAR"),
    ("item", "source_tags", "VARCHAR"),
    ("card", "relevance", "VARCHAR"),
    ("card", "relevance_ai", "VARCHAR"),
    ("card", "relevance_reason", "VARCHAR"),
    ("card", "relevance_at", "DATETIME"),
    ("card", "relevance_override", "BOOLEAN NOT NULL DEFAULT 0"),
    ("card", "category_ai", "VARCHAR"),
    ("card", "category_override", "BOOLEAN NOT NULL DEFAULT 0"),
    ("item", "origin", "VARCHAR"),
    ("category", "position", "INTEGER"),
    ("card", "feedback", "VARCHAR"),
    ("card", "feedback_at", "DATETIME"),
    ("card", "category_confirmed", "BOOLEAN NOT NULL DEFAULT 0"),
    # Feeds tab: durable join key between collected RSS items and the Feed registry.
    ("item", "feed_url", "VARCHAR"),
    ("card", "relevance_score", "INTEGER"),
    # Daily Brief: which brief covered this card (null = not yet briefed).
    ("card", "brief_id", "INTEGER"),
    # Publish-day windowing: the local calendar day this brief windows on,
    # and whether a person has reviewed it. Both default to their pre-migration values.
    ("brief", "publish_day", "TEXT NOT NULL DEFAULT ''"),
    ("brief", "reviewed", "BOOLEAN NOT NULL DEFAULT 0"),
    # Structured, card-visible fetch-failure record. All nullable so an existing Content
    # row (and every fetch lane that never sets them) is unaffected.
    ("content", "detected_type", "VARCHAR"),
    ("content", "tier_reached", "VARCHAR"),
    ("content", "http_status", "INTEGER"),
    ("content", "error_class", "VARCHAR"),
    # Which model a background job used, and the Claude usage it reported.
    ("claudejob", "model", "VARCHAR"),
    ("claudejob", "usage_five_hour", "FLOAT"),
    ("claudejob", "usage_week", "FLOAT"),
]


def create_db_engine(db_path: Path) -> Engine:
    """Create the SQLite engine for the given file, creating parent dirs as needed.

    WAL mode allows the service (single writer) and an occasional CLI reader to
    coexist; busy_timeout makes readers wait instead of erroring.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create missing tables, add later columns, and the full-text search index."""
    SQLModel.metadata.create_all(engine)
    _apply_column_migrations(engine)
    _create_fts(engine)


def check_db_integrity(engine: Engine) -> bool:
    """Return True if the database passes SQLite's quick integrity check.

    A corrupt operational DB (the 2026-06-28 incident) should surface via /api/health rather
    than crash-loop the service. Any error, or a non-'ok' result, means not-ok.
    """
    try:
        with Session(engine) as session:
            row = session.exec(text("PRAGMA quick_check")).first()
    except Exception:
        return False
    return row is not None and row[0] == "ok"


def _create_fts(engine: Engine) -> None:
    """Create the FTS5 indexes (idempotent): stored full text and chats.

    chat_fts is deliberately its own table rather than a reuse of content_fts: that index is
    keyed by item_id and its search joins to Card/Item, and a chat message is neither.
    """
    with Session(engine) as session:
        session.exec(
            text("CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(body, item_id UNINDEXED)")
        )
        session.exec(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chat_fts USING "
                "fts5(body, message_id UNINDEXED, thread_id UNINDEXED)"
            )
        )
        session.commit()


def _apply_column_migrations(engine: Engine) -> None:
    """Add columns from _ADDED_COLUMNS that an older DB is missing (no data loss)."""
    with Session(engine) as session:
        for table, column, ddl in _ADDED_COLUMNS:
            existing = {row[1] for row in session.exec(text(f"PRAGMA table_info({table})")).all()}
            if column not in existing:
                session.exec(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        session.commit()


def backfill_rss_feed_urls(engine: Engine, reader_db_path: Path) -> None:
    """Back-fill Item.feed_url for legacy RSS items that were collected before 0.13.0.

    Before 0.13.0 the RSS collector did not populate Item.feed_url, so those rows
    remained NULL and were never counted in the Feeds tab.  The reader.db
    already knows which entry belongs to which feed (entries.feed = canonical feed URL),
    so we can close the gap by joining on the shared key: Item.external_id = entries.id.

    Only items with source='rss' and feed_url IS NULL are touched; already-attributed
    items and non-RSS items are left unchanged.  The operation is idempotent: running it
    twice is safe.  If reader.db does not exist (fresh install, or tests without a reader
    DB) the function returns silently.

    Args:
        engine:          SQLAlchemy engine pointing at the Spyglass application DB.
        reader_db_path:  Path to the reader SQLite DB (produced by the reader library).
    """
    # Fast path: once the one-time backfill has run, every rss item already has a feed_url, so
    # there is nothing to do -- skip re-reading reader.db and re-running UPDATEs on every startup.
    with Session(engine) as session:
        pending = session.execute(
            text("SELECT COUNT(*) FROM item WHERE source = 'rss' AND feed_url IS NULL")
        ).scalar()
    if not pending:
        return

    if not reader_db_path.exists():
        return

    try:
        reader_conn = sqlite3.connect(str(reader_db_path))
        try:
            # Fetch the full (entry_id, feed_url) map from reader.db.
            rows = reader_conn.execute("SELECT id, feed FROM entries").fetchall()
        finally:
            reader_conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("backfill_rss_feed_urls: could not read reader.db at %s", reader_db_path)
        return

    if not rows:
        return

    # UPDATE in bulk using the Spyglass engine.  We pass each (feed_url, external_id)
    # pair; the WHERE clause ensures we only touch NULL, rss rows.  Guarded so a write failure
    # logs and continues rather than crashing startup -- _run_backup has already snapshotted the
    # DB at this point, so nothing is lost.
    try:
        with Session(engine) as session:
            updated = 0
            for entry_id, feed_url in rows:
                result = session.exec(
                    text(
                        "UPDATE item SET feed_url = :feed_url"
                        " WHERE external_id = :ext_id AND source = 'rss' AND feed_url IS NULL"
                    ),
                    params={"feed_url": feed_url, "ext_id": entry_id},
                )
                updated += result.rowcount  # type: ignore[union-attr]
            session.commit()
    except Exception:  # noqa: BLE001 -- a legacy-data backfill must never take down startup
        logger.exception(
            "backfill_rss_feed_urls: UPDATE pass failed; skipping (DB was backed up pre-backfill)"
        )
        return

    if updated:
        logger.info("backfill_rss_feed_urls: attributed %d legacy RSS item(s) to their feeds", updated)
