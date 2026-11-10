"""Tests for the feeds REST API.

All tests use a file:// fixture feed or monkeypatch the validator so no network
calls are made. The test-client pattern mirrors test_cards_api.py exactly.
"""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Feed, Item

# Local file:// fixture used as a valid feed URL (same file the feed-registry tests use).
FEED_FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_client(tmp_path: Path) -> TestClient:
    """Build a TestClient backed by an in-process SQLite database."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


def _mock_validator(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
    """No-network validator stub: accepts any URL as a valid RSS feed.

    Args:
        resolved_url: Ignored; not validated for real.
        reader_db_path: Ignored; no temp DB needed.

    Returns:
        Fixed (title, kind) so the happy path always succeeds.
    """
    return "Test Feed Title", "rss"


def _failing_validator(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
    """No-network validator stub: always raises NotAFeedError.

    Args:
        resolved_url: Forwarded into the error for the 422 body.
        reader_db_path: Ignored.

    Raises:
        NotAFeedError: Always, simulating a non-parseable URL.
    """
    from spyglass_service.feed_registry import NotAFeedError  # noqa: PLC0415

    raise NotAFeedError(resolved_url)


def _seed_feed_with_items(engine, feed_url: str = "https://example.com/feed") -> dict:
    """Insert a Feed row + two Item rows pointing at it, return a dict of feed attrs.

    Returns a plain dict so callers never hold a detached ORM instance across sessions.

    Args:
        engine: SQLAlchemy engine with the schema already initialised.
        feed_url: The canonical feed URL to use for both Feed and Items.

    Returns:
        Dict with 'id', 'feed_url', 'name', 'kind', 'enabled' captured inside the session.
    """
    with Session(engine) as session:
        feed = Feed(
            feed_url=feed_url,
            name="Example Feed",
            kind="rss",
            added_via="manual",
            enabled=True,
        )
        session.add(feed)
        session.commit()
        session.refresh(feed)
        feed_id = feed.id
        for i in range(2):
            item = Item(
                source="rss",
                external_id=f"item-{i}",
                title=f"Article {i}",
                url=f"https://example.com/a{i}",
                feed_url=feed_url,
            )
            session.add(item)
        session.commit()
        return {"id": feed_id, "feed_url": feed_url, "name": feed.name,
                "kind": feed.kind, "enabled": feed.enabled}


# ---------------------------------------------------------------------------
# GET /api/feeds
# ---------------------------------------------------------------------------


def test_get_feeds_empty(tmp_path: Path) -> None:
    """Returns an empty list when no feeds are registered."""
    with make_client(tmp_path) as client:
        resp = client.get("/api/feeds")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_feeds_returns_feed_with_item_count(tmp_path: Path) -> None:
    """Returns registered feeds with a correct item_count derived from Item rows."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine, "https://ex.com/feed")
        resp = client.get("/api/feeds")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    row = data[0]
    assert row["id"] == feed["id"]
    assert row["feed_url"] == "https://ex.com/feed"
    assert row["item_count"] == 2
    assert row["enabled"] is True
    assert row["kind"] == "rss"
    assert "last_fetch_status" in row
    assert "last_fetch_at" in row
    assert "last_error" in row
    assert "added_via" in row


def test_get_feeds_item_count_zero_when_no_items(tmp_path: Path) -> None:
    """A feed with no collected items reports item_count=0."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            feed = Feed(
                feed_url="https://empty.com/feed",
                name="Empty Feed",
                kind="rss",
                added_via="manual",
                enabled=True,
            )
            session.add(feed)
            session.commit()
        resp = client.get("/api/feeds")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["item_count"] == 0


def test_get_feeds_multiple_feeds_correct_counts(tmp_path: Path) -> None:
    """Each feed's item_count reflects only its own items."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        _seed_feed_with_items(engine, "https://feed-a.com/rss")
        with Session(engine) as session:
            feed_b = Feed(
                feed_url="https://feed-b.com/rss",
                name="Feed B",
                kind="rss",
                added_via="manual",
                enabled=True,
            )
            session.add(feed_b)
            session.commit()
            session.refresh(feed_b)
            item = Item(
                source="rss",
                external_id="only-one",
                title="Only",
                url="https://feed-b.com/a",
                feed_url="https://feed-b.com/rss",
            )
            session.add(item)
            session.commit()
        resp = client.get("/api/feeds")
    assert resp.status_code == 200
    data = resp.json()
    counts = {row["feed_url"]: row["item_count"] for row in data}
    assert counts["https://feed-a.com/rss"] == 2
    assert counts["https://feed-b.com/rss"] == 1


# ---------------------------------------------------------------------------
# POST /api/feeds
# ---------------------------------------------------------------------------


def test_post_feed_valid_returns_feed_out(tmp_path: Path) -> None:
    """A valid feed URL returns a FeedOut with the resolved feed data."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            resp = client.post("/api/feeds", json={"url": "https://example.com/feed"})
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["feed_url"] == "https://example.com/feed"
    assert data["name"] == "Test Feed Title"
    assert data["kind"] == "rss"
    assert data["enabled"] is True
    assert "id" in data
    assert "item_count" in data


def test_post_feed_not_a_feed_returns_422(tmp_path: Path) -> None:
    """A URL that is not a valid feed returns 422 with kind=not_a_feed."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _failing_validator):
            resp = client.post("/api/feeds", json={"url": "https://notafeed.example.com"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "not_a_feed"
    assert "url" in detail


def test_post_feed_blocked_says_why(tmp_path: Path) -> None:
    """A site that refuses Spyglass is reported as blocked, with a plain reason."""
    from spyglass_service.feed_registry import NotAFeedError  # noqa: PLC0415

    def blocked(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
        raise NotAFeedError(resolved_url, "blocked")

    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", blocked):
            resp = client.post("/api/feeds", json={"url": "https://guarded.example.com/feed"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "blocked"
    assert "refused" in detail["reason"]


def test_post_feed_dedupes_existing_url(tmp_path: Path) -> None:
    """Posting an already-registered URL returns the existing feed (no duplicate)."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            r1 = client.post("/api/feeds", json={"url": "https://example.com/feed"})
            r2 = client.post("/api/feeds", json={"url": "https://example.com/feed"})
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)
    assert r1.json()["id"] == r2.json()["id"]


# ---------------------------------------------------------------------------
# POST /api/feeds — optional name field
# ---------------------------------------------------------------------------


def test_post_feed_with_name_stores_name_and_sets_overridden(tmp_path: Path) -> None:
    """POST /api/feeds {url, name} -> FeedOut has the provided name and name_overridden=True."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            resp = client.post(
                "/api/feeds",
                json={"url": "https://example.com/feed", "name": "My Friendly Name"},
            )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["name"] == "My Friendly Name"
    assert data["name_overridden"] is True


def test_post_feed_without_name_derives_name_unchanged(tmp_path: Path) -> None:
    """POST /api/feeds {url} (no name) -> unchanged behaviour: name derived, overridden=False."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            resp = client.post("/api/feeds", json={"url": "https://example.com/feed"})
    assert resp.status_code in (200, 201)
    data = resp.json()
    # The mock validator returns "Test Feed Title".
    assert data["name"] == "Test Feed Title"
    assert data["name_overridden"] is False


# ---------------------------------------------------------------------------
# PATCH /api/feeds/{id}
# ---------------------------------------------------------------------------


def test_patch_feed_set_enabled_false(tmp_path: Path) -> None:
    """PATCH enabled=false disables the feed."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine)
        resp = client.patch(f"/api/feeds/{feed['id']}", json={"enabled": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False


def test_patch_feed_rename_sets_name_overridden(tmp_path: Path) -> None:
    """PATCH name sets the display name and marks name_overridden=True."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine)
        resp = client.patch(f"/api/feeds/{feed['id']}", json={"name": "My Custom Name"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Custom Name"
    assert data["name_overridden"] is True


def test_patch_feed_unknown_id_returns_404(tmp_path: Path) -> None:
    """PATCH on a non-existent id returns 404."""
    with make_client(tmp_path) as client:
        resp = client.patch("/api/feeds/99999", json={"enabled": False})
    assert resp.status_code == 404


def test_patch_feed_enable_disable_roundtrip(tmp_path: Path) -> None:
    """Disabling then re-enabling a feed leaves enabled=True."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine)
        client.patch(f"/api/feeds/{feed['id']}", json={"enabled": False})
        resp = client.patch(f"/api/feeds/{feed['id']}", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


# ---------------------------------------------------------------------------
# DELETE /api/feeds/{id}
# ---------------------------------------------------------------------------


def test_delete_feed_unknown_id_returns_404(tmp_path: Path) -> None:
    """DELETE on a non-existent id returns 404."""
    with make_client(tmp_path) as client:
        resp = client.delete("/api/feeds/99999")
    assert resp.status_code == 404


def test_delete_feed_removes_feed_row(tmp_path: Path) -> None:
    """After DELETE, the feed no longer appears in GET /api/feeds."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine)
        # Also create cards for the items so delete_cards has something to purge.
        with Session(engine) as session:
            items = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(Item).where(
                    Item.feed_url == feed["feed_url"]
                )
            ).all()
            for item in items:
                card = Card(item_id=item.id, summary="s")
                session.add(card)
            session.commit()
        resp = client.delete(f"/api/feeds/{feed['id']}")
    assert resp.status_code == 200
    result = resp.json()
    assert result["deleted"] is True

    with make_client(tmp_path) as client2:
        feeds = client2.get("/api/feeds").json()
    assert feeds == []


def test_delete_feed_removes_cards_and_tombstones(tmp_path: Path) -> None:
    """DELETE purges the feed's cards and writes tombstones blocking re-collection."""
    from spyglass_service.models import Tombstone  # noqa: PLC0415

    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed = _seed_feed_with_items(engine)
        with Session(engine) as session:
            items = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(Item).where(
                    Item.feed_url == feed["feed_url"]
                )
            ).all()
            item_ext_ids = [(i.source, i.external_id) for i in items]
            for item in items:
                card = Card(item_id=item.id, summary="s")
                session.add(card)
            session.commit()

        resp = client.delete(f"/api/feeds/{feed['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cards_removed"] == 2

        # Verify tombstones were written.
        with Session(engine) as session:
            for source, ext_id in item_ext_ids:
                tombstone = session.exec(
                    __import__("sqlmodel", fromlist=["select"]).select(Tombstone).where(
                        Tombstone.source == source,
                        Tombstone.external_id == ext_id,
                    )
                ).first()
                assert tombstone is not None, f"Missing tombstone for {source}/{ext_id}"


# ---------------------------------------------------------------------------
# POST /api/feeds/import
# ---------------------------------------------------------------------------


# Minimal valid OPML fixture for import tests.
_IMPORT_OPML = """\
<?xml version="1.0" encoding="utf-8"?>
<opml version="2.0">
  <head><title>Import Test</title></head>
  <body>
    <outline type="rss" text="Feed X" xmlUrl="https://x.example.com/feed"/>
    <outline type="rss" text="Feed Y" xmlUrl="https://y.example.com/rss"/>
  </body>
</opml>
"""

_IMPORT_MARKDOWN = """\
- [Feed X](https://x.example.com/feed)
- [Feed Y](https://y.example.com/rss)
"""


def test_import_opml_adds_new_feeds(tmp_path: Path) -> None:
    """POST /api/feeds/import with valid OPML adds new feeds and returns correct counts."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            resp = client.post(
                "/api/feeds/import",
                content=_IMPORT_OPML,
                headers={"Content-Type": "text/plain"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 2
    assert data["skipped"] == 0


def test_import_markdown_adds_new_feeds(tmp_path: Path) -> None:
    """POST /api/feeds/import with markdown content adds feeds and returns correct counts."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            resp = client.post(
                "/api/feeds/import",
                content=_IMPORT_MARKDOWN,
                headers={"Content-Type": "text/plain"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 2
    assert data["skipped"] == 0


def test_import_skips_duplicate_feeds(tmp_path: Path) -> None:
    """POST /api/feeds/import skips URLs that are already in the registry."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            # First import — both added
            r1 = client.post(
                "/api/feeds/import",
                content=_IMPORT_OPML,
                headers={"Content-Type": "text/plain"},
            )
            assert r1.json()["added"] == 2

            # Second import — both are now dupes
            r2 = client.post(
                "/api/feeds/import",
                content=_IMPORT_OPML,
                headers={"Content-Type": "text/plain"},
            )
    assert r2.status_code == 200
    data = r2.json()
    assert data["added"] == 0
    assert data["skipped"] == 2


def test_import_skips_non_feed_urls(tmp_path: Path) -> None:
    """POST /api/feeds/import skips URLs that are not valid feeds (NotAFeedError)."""
    opml_with_bad = """\
<?xml version="1.0" encoding="utf-8"?>
<opml version="2.0">
  <head><title>Mixed</title></head>
  <body>
    <outline type="rss" text="Good" xmlUrl="https://good.example.com/feed"/>
    <outline type="rss" text="Bad" xmlUrl="https://bad.example.com/notafeed"/>
  </body>
</opml>
"""

    def partial_validator(resolved_url: str, reader_db_path: Path) -> tuple[str, str]:
        """Accept 'good' URLs; reject 'bad' ones.

        Args:
            resolved_url: URL to validate.
            reader_db_path: Ignored.

        Returns:
            Fixed title/kind for good URLs.

        Raises:
            NotAFeedError: For URLs containing 'bad'.
        """
        from spyglass_service.feed_registry import NotAFeedError  # noqa: PLC0415

        if "bad" in resolved_url:
            raise NotAFeedError(resolved_url)
        return "Good Feed", "rss"

    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", partial_validator):
            resp = client.post(
                "/api/feeds/import",
                content=opml_with_bad,
                headers={"Content-Type": "text/plain"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 1
    assert data["skipped"] == 1


def test_import_malformed_opml_returns_422(tmp_path: Path) -> None:
    """POST /api/feeds/import with unparseable OPML returns 422."""
    with make_client(tmp_path) as client:
        resp = client.post(
            "/api/feeds/import",
            content="<opml><body><outline xmlUrl='https://x.com/f'",
            headers={"Content-Type": "text/plain"},
        )
    assert resp.status_code == 422


def test_import_mixed_opml_and_dupes_counts_correctly(tmp_path: Path) -> None:
    """Importing OPML where one URL is new and one is a dupe counts each correctly."""
    with make_client(tmp_path) as client:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            # Seed one feed directly
            client.post("/api/feeds", json={"url": "https://x.example.com/feed"})

            # Now import OPML that has the seeded URL + a new one
            resp = client.post(
                "/api/feeds/import",
                content=_IMPORT_OPML,
                headers={"Content-Type": "text/plain"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 1
    assert data["skipped"] == 1


# ---------------------------------------------------------------------------
# GET /api/feeds/export
# ---------------------------------------------------------------------------


def _seed_feed_only(engine, feed_url: str, name: str = "Seeded Feed") -> None:
    """Insert a Feed row (no items) — avoids the external_id collision in _seed_feed_with_items.

    Args:
        engine: SQLAlchemy engine with schema initialised.
        feed_url: Canonical feed URL for the Feed row.
        name: Display name for the feed.
    """
    with Session(engine) as session:
        feed = Feed(feed_url=feed_url, name=name, kind="rss", added_via="manual", enabled=True)
        session.add(feed)
        session.commit()


def test_export_opml_default_returns_opml(tmp_path: Path) -> None:
    """GET /api/feeds/export (default format=opml) returns OPML text with all feeds."""
    from spyglass_service.feed_io import parse_opml  # noqa: PLC0415

    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        _seed_feed_only(engine, "https://export-a.com/feed", "Feed A")
        _seed_feed_only(engine, "https://export-b.com/rss", "Feed B")
        resp = client.get("/api/feeds/export")

    assert resp.status_code == 200
    assert "opml" in resp.headers.get("content-disposition", "").lower()
    urls = parse_opml(resp.text)
    assert "https://export-a.com/feed" in urls
    assert "https://export-b.com/rss" in urls


def test_export_opml_explicit_format_returns_opml(tmp_path: Path) -> None:
    """GET /api/feeds/export?format=opml returns OPML with correct content-type."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        _seed_feed_with_items(engine, "https://exportc.com/feed")
        resp = client.get("/api/feeds/export?format=opml")

    assert resp.status_code == 200
    content_type = resp.headers.get("content-type", "")
    assert "xml" in content_type or "opml" in content_type
    assert "https://exportc.com/feed" in resp.text


def test_export_markdown_returns_parseable_markdown(tmp_path: Path) -> None:
    """GET /api/feeds/export?format=markdown returns markdown with all feed URLs."""
    from spyglass_service.collectors.feedlist import parse_feed_list  # noqa: PLC0415

    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        _seed_feed_with_items(engine, "https://md-export.com/feed")
        resp = client.get("/api/feeds/export?format=markdown")

    assert resp.status_code == 200
    content_type = resp.headers.get("content-type", "")
    assert "markdown" in content_type or "text" in content_type
    urls = parse_feed_list(resp.text)
    assert "https://md-export.com/feed" in urls


def test_export_empty_registry_returns_valid_document(tmp_path: Path) -> None:
    """GET /api/feeds/export with no feeds returns a valid (possibly empty) document."""
    with make_client(tmp_path) as client:
        resp = client.get("/api/feeds/export?format=opml")
    assert resp.status_code == 200
    # Should be parseable even when empty
    from spyglass_service.feed_io import parse_opml  # noqa: PLC0415

    assert parse_opml(resp.text) == []


def test_export_bad_format_returns_422(tmp_path: Path) -> None:
    """GET /api/feeds/export?format=csv returns 422 for unsupported format."""
    with make_client(tmp_path) as client:
        resp = client.get("/api/feeds/export?format=csv")
    assert resp.status_code == 422


def test_export_opml_round_trips_to_import(tmp_path: Path) -> None:
    """Export OPML then import it into a fresh registry: yields the same URL set."""
    from spyglass_service.feed_io import parse_opml  # noqa: PLC0415

    # First client: seed feeds + export
    with make_client(tmp_path / "orig") as client:
        engine = client.app.state.engine
        _seed_feed_only(engine, "https://rt-a.com/feed", "RT Feed A")
        _seed_feed_only(engine, "https://rt-b.com/rss", "RT Feed B")
        export_resp = client.get("/api/feeds/export?format=opml")
    assert export_resp.status_code == 200
    exported_opml = export_resp.text

    # Verify exported URLs
    exported_urls = parse_opml(exported_opml)
    assert set(exported_urls) == {"https://rt-a.com/feed", "https://rt-b.com/rss"}

    # Second client: fresh registry, import the exported OPML
    with make_client(tmp_path / "fresh") as client2:
        with patch("spyglass_service.feed_registry._validate_feed", _mock_validator):
            import_resp = client2.post(
                "/api/feeds/import",
                content=exported_opml,
                headers={"Content-Type": "text/plain"},
            )
        assert import_resp.json()["added"] == 2

        feeds_resp = client2.get("/api/feeds")
    imported_urls = {f["feed_url"] for f in feeds_resp.json()}
    assert imported_urls == set(exported_urls)
