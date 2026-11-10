"""Tests for building the active collector set from the Feed registry."""

from pathlib import Path

from sqlmodel import Session, create_engine
from sqlmodel import SQLModel

from spyglass_service.collectors.factory import build_collectors
from spyglass_service.collectors.rss import RssCollector
from spyglass_service.config import Settings
from spyglass_service.models import Feed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path):
    """Create an in-memory-ish SQLite engine with schema created."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _insert_feed(engine, feed_url: str, enabled: bool = True) -> None:
    """Insert a Feed row directly (bypasses validation -- unit tests only)."""
    with Session(engine) as session:
        session.add(
            Feed(
                feed_url=feed_url,
                name="Test Feed",
                kind="rss",
                added_via="manual",
                enabled=enabled,
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Registry-driven contract
# ---------------------------------------------------------------------------


def test_empty_registry_and_no_note_yields_no_rss_collector(tmp_path: Path) -> None:
    """No Feed rows and no note -> no RSS collector.

    seed_from_note does nothing (empty registry, no note path), so the RSS
    collector must not appear in the result.
    """
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = _make_engine(tmp_path)
    collectors = build_collectors(settings, engine)
    assert collectors == []


def test_enabled_feed_row_produces_rss_collector(tmp_path: Path) -> None:
    """A single enabled Feed row causes an RssCollector to appear."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = _make_engine(tmp_path)
    _insert_feed(engine, "https://example.test/feed.xml", enabled=True)
    names = [c.name for c in build_collectors(settings, engine)]
    assert names == ["rss"]


def test_only_enabled_rows_are_collected(tmp_path: Path) -> None:
    """Disabled rows must be excluded from the RSS collector's URL list."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = _make_engine(tmp_path)
    _insert_feed(engine, "https://example.test/enabled.xml", enabled=True)
    _insert_feed(engine, "https://example.test/disabled.xml", enabled=False)

    collectors = build_collectors(settings, engine)
    assert len(collectors) == 1
    rss = collectors[0]
    assert isinstance(rss, RssCollector)
    # The disabled URL must not appear in the private url list.
    assert "https://example.test/disabled.xml" not in rss._feed_urls
    assert "https://example.test/enabled.xml" in rss._feed_urls


def test_all_disabled_rows_yields_no_rss_collector(tmp_path: Path) -> None:
    """When all Feed rows are disabled the RSS collector is omitted entirely."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = _make_engine(tmp_path)
    _insert_feed(engine, "https://example.test/a.xml", enabled=False)
    _insert_feed(engine, "https://example.test/b.xml", enabled=False)
    collectors = build_collectors(settings, engine)
    assert collectors == []


def test_seed_from_note_populates_registry_before_build(tmp_path: Path) -> None:
    """A feed note is seeded into an empty registry on the first build_collectors call."""
    note = tmp_path / "feeds.md"
    note.write_text("- https://example.test/seeded.xml", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path, feed_note_path=note)
    engine = _make_engine(tmp_path)

    # Registry is empty before the call -- build_collectors seeds it.
    names = [c.name for c in build_collectors(settings, engine)]
    assert names == ["rss"]


def test_feed_note_ignored_once_registry_is_seeded(tmp_path: Path) -> None:
    """A note URL is not double-collected once registry rows exist.

    When the registry is non-empty, seed_from_note is a no-op. The note path
    should have NO effect on collection beyond the first (seeding) call.
    """
    note = tmp_path / "feeds.md"
    note.write_text("- https://example.test/from-note.xml", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path, feed_note_path=note)
    engine = _make_engine(tmp_path)

    # Pre-seed with a different URL so the registry is already non-empty.
    _insert_feed(engine, "https://example.test/registry.xml", enabled=True)

    collectors = build_collectors(settings, engine)
    assert len(collectors) == 1
    rss = collectors[0]
    # Only the registry row's URL should appear, not the note URL.
    assert "https://example.test/from-note.xml" not in rss._feed_urls
    assert "https://example.test/registry.xml" in rss._feed_urls


def test_raindrop_token_enables_the_raindrop_collector(tmp_path: Path) -> None:
    """A configured raindrop token activates Raindrop polling (unchanged branch)."""
    settings = Settings(_env_file=None, data_dir=tmp_path, raindrop_token="tok")
    engine = _make_engine(tmp_path)
    names = [c.name for c in build_collectors(settings, engine)]
    assert names == ["raindrop"]


def test_raindrop_and_rss_collectors_both_present(tmp_path: Path) -> None:
    """Both RSS (from registry) and Raindrop (from token) appear together."""
    settings = Settings(_env_file=None, data_dir=tmp_path, raindrop_token="tok")
    engine = _make_engine(tmp_path)
    _insert_feed(engine, "https://example.test/feed.xml", enabled=True)
    names = [c.name for c in build_collectors(settings, engine)]
    assert "rss" in names
    assert "raindrop" in names
