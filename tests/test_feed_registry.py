"""Tests for feed_registry: pure CRUD helpers + seed_from_note (no network, no FastAPI)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.feed_registry import (
    NotAFeedError,
    add_feed,
    delete_feed,
    get_feed,
    list_feeds,
    seed_from_note,
    update_feed,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FEED_FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"
# A file that exists but is not a valid feed (plain text).
NON_FEED_FIXTURE = Path(__file__).parent / "fixtures" / "not_a_feed.txt"


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    """In-process SQLite session with all tables created; discarded after each test."""
    engine = create_db_engine(tmp_path / "test.db")
    init_db(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def feed_url() -> str:
    """Local file:// URL pointing at the RSS fixture; reader can parse it directly."""
    return str(FEED_FIXTURE)


@pytest.fixture()
def non_feed_url() -> str:
    """Local file:// URL pointing at a plain-text file that is NOT a valid feed."""
    return str(NON_FEED_FIXTURE)


# ---------------------------------------------------------------------------
# Helpers — make validator monkeypatching explicit
# ---------------------------------------------------------------------------


def _mock_validator(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
    """Return (title, kind) without network; used for add_feed happy-path tests."""
    title = "Test Feed"
    kind = "youtube" if "feeds/videos.xml" in resolved_url else "rss"
    return title, kind


def _failing_validator(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
    """Simulate a non-parseable URL raising NotAFeedError from inside the validator."""
    from spyglass_service.feed_registry import NotAFeedError  # noqa: PLC0415

    raise NotAFeedError(resolved_url)


# ---------------------------------------------------------------------------
# list_feeds / get_feed
# ---------------------------------------------------------------------------


def test_list_feeds_empty_on_fresh_db(session: Session) -> None:
    """A newly initialised registry has no feeds."""
    assert list_feeds(session) == []


def test_get_feed_returns_none_for_missing_id(session: Session) -> None:
    """get_feed returns None rather than raising when the id is absent."""
    assert get_feed(session, 9999) is None


# ---------------------------------------------------------------------------
# add_feed — happy path
# ---------------------------------------------------------------------------


def test_add_feed_inserts_row_with_resolved_url(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """add_feed stores the RESOLVED url (= input for a local file, no rewrite needed)."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert feed.feed_url == feed_url


def test_add_feed_populates_name_from_feed_title(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """add_feed sets name from the feed's own title element."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert feed.name == "Sample Research Feed"


def test_add_feed_sets_kind_rss_for_plain_feed(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """A regular RSS/Atom feed gets kind='rss'."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert feed.kind == "rss"


def test_add_feed_sets_added_via_manual(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """Feeds added via add_feed have added_via='manual'."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert feed.added_via == "manual"


def test_add_feed_sets_enabled_true(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """A newly added feed is enabled by default."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert feed.enabled is True


def test_add_feed_youtube_feed_url_gets_kind_youtube(
    session: Session, tmp_path: Path
) -> None:
    """A resolved youtube feeds/videos.xml URL gets kind='youtube'."""
    yt_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCHnyfMqiRRG1u-2MsSQLbXA"
    with patch(
        "spyglass_service.feed_registry._validate_feed",
        side_effect=_mock_validator,
    ):
        feed = add_feed(session, yt_url, reader_db_path=tmp_path / "reader.db")
    assert feed.kind == "youtube"


def test_add_feed_row_is_retrievable_via_get_feed(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """The feed returned by add_feed can be retrieved by id via get_feed."""
    inserted = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert inserted.id is not None
    fetched = get_feed(session, inserted.id)
    assert fetched is not None
    assert fetched.feed_url == feed_url


# ---------------------------------------------------------------------------
# add_feed — duplicate (dedupe)
# ---------------------------------------------------------------------------


def test_add_feed_dedupes_same_resolved_url(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """Adding the same URL twice returns the existing row; no second insert."""
    first = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    second = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    assert first.id == second.id
    assert len(list_feeds(session)) == 1


# ---------------------------------------------------------------------------
# add_feed — optional name kwarg
# ---------------------------------------------------------------------------


def test_add_feed_with_name_sets_name_and_overridden_flag(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """add_feed(name=...) stores the provided name and marks name_overridden=True."""
    feed = add_feed(session, feed_url, name="My Custom Feed", reader_db_path=tmp_path / "reader.db")
    assert feed.name == "My Custom Feed"
    assert feed.name_overridden is True


def test_add_feed_without_name_derives_name_and_overridden_false(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """add_feed without name derives name from the feed title; name_overridden stays False."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    # Title comes from the fixture feed XML ("Sample Research Feed").
    assert feed.name == "Sample Research Feed"
    assert feed.name_overridden is False


def test_add_feed_dedupe_with_name_does_not_rename_existing(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """On a dedupe hit, re-adding with a different name must NOT rename the existing row."""
    first = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    original_name = first.name
    second = add_feed(session, feed_url, name="New Name", reader_db_path=tmp_path / "reader.db")
    # Same row returned.
    assert second.id == first.id
    # Name must be unchanged.
    assert second.name == original_name
    assert second.name_overridden is False


def test_add_feed_dedupe_with_name_does_not_rename_existing_when_name_overridden(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """On a dedupe hit, re-adding must NOT rename a row that already has name_overridden=True."""
    first = add_feed(session, feed_url, name="Original", reader_db_path=tmp_path / "reader.db")
    assert first.name == "Original"
    assert first.name_overridden is True

    second = add_feed(session, feed_url, name="New Name", reader_db_path=tmp_path / "reader.db")
    # Same row returned — name must remain the original overridden value.
    assert second.id == first.id
    assert second.name == "Original"
    assert second.name_overridden is True


# ---------------------------------------------------------------------------
# add_feed — non-feed rejection
# ---------------------------------------------------------------------------


def test_add_feed_raises_not_a_feed_error_for_non_feed(
    session: Session, tmp_path: Path, non_feed_url: str
) -> None:
    """A URL that does not parse as a feed raises NotAFeedError (never inserts a row)."""
    with pytest.raises(NotAFeedError):
        add_feed(session, non_feed_url, reader_db_path=tmp_path / "reader.db")
    assert list_feeds(session) == []


def test_not_a_feed_error_carries_the_url(
    session: Session, tmp_path: Path, non_feed_url: str
) -> None:
    """NotAFeedError message contains the offending URL so a caller can forward it."""
    with pytest.raises(NotAFeedError) as exc_info:
        add_feed(session, non_feed_url, reader_db_path=tmp_path / "reader.db")
    assert non_feed_url in str(exc_info.value)


# ---------------------------------------------------------------------------
# update_feed
# ---------------------------------------------------------------------------


def test_update_feed_sets_name_and_name_overridden(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """Renaming a feed sets the new name and marks name_overridden=True."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    updated = update_feed(session, feed.id, name="My Custom Name")  # type: ignore[arg-type]
    assert updated is not None
    assert updated.name == "My Custom Name"
    assert updated.name_overridden is True


def test_update_feed_enabled_toggle(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """Disabling and re-enabling a feed updates the enabled flag correctly."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    disabled = update_feed(session, feed.id, enabled=False)  # type: ignore[arg-type]
    assert disabled is not None
    assert disabled.enabled is False
    enabled = update_feed(session, feed.id, enabled=True)  # type: ignore[arg-type]
    assert enabled is not None
    assert enabled.enabled is True


def test_update_feed_bumps_updated_at(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """updated_at is refreshed on every update_feed call."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    original_ts = feed.updated_at
    updated = update_feed(session, feed.id, name="New Name")  # type: ignore[arg-type]
    assert updated is not None
    assert updated.updated_at >= original_ts


def test_update_feed_returns_none_for_missing_id(session: Session) -> None:
    """update_feed returns None (not an error) when the id does not exist."""
    result = update_feed(session, 9999, name="Ghost")
    assert result is None


def test_update_feed_name_only_does_not_flip_enabled(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """Renaming should not change the enabled state."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    updated = update_feed(session, feed.id, name="New Name")  # type: ignore[arg-type]
    assert updated is not None
    assert updated.enabled is True  # unchanged


# ---------------------------------------------------------------------------
# delete_feed
# ---------------------------------------------------------------------------


def test_delete_feed_removes_the_row(
    session: Session, tmp_path: Path, feed_url: str
) -> None:
    """delete_feed removes the row; the registry is empty afterwards."""
    feed = add_feed(session, feed_url, reader_db_path=tmp_path / "reader.db")
    result = delete_feed(session, feed.id)  # type: ignore[arg-type]
    assert result is True
    assert list_feeds(session) == []


def test_delete_feed_returns_false_for_missing_id(session: Session) -> None:
    """delete_feed returns False when no row matched the id."""
    assert delete_feed(session, 9999) is False


# ---------------------------------------------------------------------------
# seed_from_note
# ---------------------------------------------------------------------------


# Fake feed URLs used in seed tests — parse_feed_list only matches http(s)://, so
# we use https:// URLs here. seed_from_note does NOT network-validate, so these
# are never fetched; they just need to look like URLs.
SEED_URL_1 = "https://example.test/feeds/tech.xml"
SEED_URL_2 = "https://other.test/rss.xml"


@pytest.fixture()
def note_path(tmp_path: Path) -> Path:
    """A minimal feed-list note containing two https:// feed URLs."""
    note = tmp_path / "feeds.md"
    note.write_text(f"# My feeds\n- {SEED_URL_1}\n- {SEED_URL_2}\n")
    return note


@pytest.fixture()
def single_url_note(tmp_path: Path) -> Path:
    """A note containing exactly one https:// feed URL."""
    note = tmp_path / "feeds.md"
    note.write_text(f"# My feeds\n- {SEED_URL_1}\n")
    return note


def test_seed_from_note_inserts_feeds_from_note(
    session: Session, tmp_path: Path, note_path: Path
) -> None:
    """seed_from_note reads the note, resolves each URL, and inserts Feed rows."""
    settings = Settings(feed_note_path=note_path)
    count = seed_from_note(settings, session)
    assert count == 2
    feeds = list_feeds(session)
    assert len(feeds) == 2
    feed_urls = {f.feed_url for f in feeds}
    assert SEED_URL_1 in feed_urls
    assert SEED_URL_2 in feed_urls


def test_seed_from_note_sets_added_via_import(
    session: Session, tmp_path: Path, single_url_note: Path
) -> None:
    """Seeded feeds have added_via='import', not 'manual'."""
    settings = Settings(feed_note_path=single_url_note)
    seed_from_note(settings, session)
    feeds = list_feeds(session)
    assert len(feeds) == 1
    assert feeds[0].added_via == "import"


def test_seed_from_note_sets_provisional_name_as_host(
    session: Session, tmp_path: Path, single_url_note: Path
) -> None:
    """Seeded feeds get a provisional name = hostname (no network validation)."""
    settings = Settings(feed_note_path=single_url_note)
    seed_from_note(settings, session)
    feeds = list_feeds(session)
    assert len(feeds) == 1
    # For https://example.test/feeds/tech.xml the host is example.test.
    assert feeds[0].name == "example.test"


def test_seed_from_note_is_idempotent_returns_zero_when_non_empty(
    session: Session, tmp_path: Path, single_url_note: Path
) -> None:
    """seed_from_note returns 0 and inserts nothing when the registry is non-empty."""
    settings = Settings(feed_note_path=single_url_note)
    seed_from_note(settings, session)
    second_count = seed_from_note(settings, session)
    assert second_count == 0
    assert len(list_feeds(session)) == 1  # still only one


def test_seed_from_note_skips_when_no_feed_note_path(
    session: Session, tmp_path: Path
) -> None:
    """seed_from_note returns 0 gracefully when feed_note_path is not configured."""
    settings = Settings(feed_note_path=None)
    count = seed_from_note(settings, session)
    assert count == 0
    assert list_feeds(session) == []


def test_seed_from_note_skips_when_note_path_missing(
    session: Session, tmp_path: Path
) -> None:
    """seed_from_note returns 0 when the configured note file does not exist."""
    settings = Settings(feed_note_path=tmp_path / "nonexistent.md")
    count = seed_from_note(settings, session)
    assert count == 0


def test_seed_from_note_dedupes_within_batch(
    session: Session, tmp_path: Path
) -> None:
    """If the same URL appears twice in the note, only one row is inserted."""
    note = tmp_path / "feeds.md"
    # Same URL listed twice.
    note.write_text(f"- {SEED_URL_1}\n- {SEED_URL_1}\n")
    settings = Settings(feed_note_path=note)
    count = seed_from_note(settings, session)
    assert count == 1
    assert len(list_feeds(session)) == 1


def test_seed_from_note_does_not_require_network(
    session: Session, tmp_path: Path, single_url_note: Path
) -> None:
    """seed_from_note must complete without making any HTTP requests (no validation)."""
    # Patch httpx.Client.send to raise if called — if no exception, no network was used.
    import httpx  # noqa: PLC0415

    def _no_network(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("seed_from_note made a network call")

    settings = Settings(feed_note_path=single_url_note)
    with patch.object(httpx.Client, "send", _no_network):
        count = seed_from_note(settings, session)
    assert count == 1
