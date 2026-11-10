"""Tests for the full-text content store: markdown stored in SQLite."""

from pathlib import Path

from sqlmodel import Session

from spyglass_service.content_store import (
    delete_content,
    get_fulltext,
    search_fulltext,
    store_fulltext,
)
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item


def make_engine(tmp_path: Path):
    """A fresh, migrated SQLite engine in the test's temp dir."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def add_item(engine, ext_id: str = "a") -> int:
    """Insert a raw item and return its id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id=ext_id, title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


def test_store_and_get_fulltext_round_trip(tmp_path: Path) -> None:
    """Stored markdown comes back with computed text_chars and the metadata."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="# Title\n\nBody",
        source_url="https://x.test/a", content_type="text/html", status="ok",
    )
    stored = get_fulltext(engine, item_id)
    assert stored is not None
    assert stored["markdown"] == "# Title\n\nBody"
    assert stored["status"] == "ok"
    assert stored["content_type"] == "text/html"
    assert stored["text_chars"] == len("# Title\n\nBody")


def test_get_fulltext_is_none_when_absent(tmp_path: Path) -> None:
    """An item with no stored content yields None, not an error."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    assert get_fulltext(engine, item_id) is None


def test_store_fulltext_replaces_so_it_stays_one_to_one(tmp_path: Path) -> None:
    """Re-storing an item's content updates in place (1:1 with the item)."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(engine, item_id=item_id, markdown="old", source_url="u", content_type="text/html", status="ok")
    store_fulltext(engine, item_id=item_id, markdown="new longer body", source_url="u", content_type="text/html", status="ok")
    stored = get_fulltext(engine, item_id)
    assert stored["markdown"] == "new longer body"
    assert stored["text_chars"] == len("new longer body")


def test_store_fulltext_records_failure_status_and_error(tmp_path: Path) -> None:
    """A failed fetch is recorded (status + error), not silently dropped."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="", source_url="u",
        content_type="", status="failed", error="HTTP 403",
    )
    stored = get_fulltext(engine, item_id)
    assert stored["status"] == "failed"
    assert stored["error"] == "HTTP 403"
    assert stored["text_chars"] == 0


def test_store_and_get_fulltext_round_trips_structured_failure_fields(tmp_path: Path) -> None:
    """detected_type/tier_reached/http_status/error_class round-trip.

    Populated on the success path too (winning tier/type), not only on failure.
    """
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="# Title\n\nBody",
        source_url="https://x.test/a", content_type="text/html", status="ok",
        detected_type="html", tier_reached="T1", http_status=200, error_class=None,
    )
    stored = get_fulltext(engine, item_id)
    assert stored["detected_type"] == "html"
    assert stored["tier_reached"] == "T1"
    assert stored["http_status"] == 200
    assert stored["error_class"] is None


def test_get_fulltext_structured_failure_fields_default_none_when_unset(tmp_path: Path) -> None:
    """A store_fulltext call that omits the new kwargs leaves them None (backward compat)."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="body", source_url="u",
        content_type="text/html", status="ok",
    )
    stored = get_fulltext(engine, item_id)
    assert stored["detected_type"] is None
    assert stored["tier_reached"] is None
    assert stored["http_status"] is None
    assert stored["error_class"] is None


def test_store_fulltext_records_structured_failure_on_give_up(tmp_path: Path) -> None:
    """A give-up failure stores the structured fields alongside the legible error."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="", source_url="u", content_type="",
        status="failed", error="blocked at T0 (HTTP 403); T1 also failed: timeout",
        detected_type="html", tier_reached="T1", http_status=403, error_class="blocked",
    )
    stored = get_fulltext(engine, item_id)
    assert stored["status"] == "failed"
    assert stored["error_class"] == "blocked"
    assert stored["tier_reached"] == "T1"
    assert stored["http_status"] == 403
    assert "blocked at T0" in stored["error"]


def test_store_fulltext_sanitizes_surrogates_in_detected_type_and_error_class(tmp_path: Path) -> None:
    """A lone surrogate in the new string fields must not crash the store."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="", source_url="u", content_type="",
        status="failed", error="boom",
        detected_type="html \ud800 kind", tier_reached="T1", http_status=403,
        error_class="blocked \udfff class",
    )
    stored = get_fulltext(engine, item_id)
    assert "\ud800" not in (stored["detected_type"] or "")
    assert "\udfff" not in (stored["error_class"] or "")


def test_search_matches_stored_full_text_with_a_snippet(tmp_path: Path) -> None:
    """FTS5 finds a word in the stored body and returns a snippet around it."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id,
        markdown="Hierarchical memory eviction policy matters most.",
        source_url="u", content_type="text/html", status="ok",
    )
    results = search_fulltext(engine, "eviction")
    assert [r["item_id"] for r in results] == [item_id]
    assert "eviction" in results[0]["snippet"].lower()


def test_search_falls_back_to_title_summary_when_no_full_text(tmp_path: Path) -> None:
    """Items without stored full text are still found via title/summary."""
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(source="rss", external_id="b", title="Long-horizon planning in agents",
                    url="https://x.test", summary="goal decomposition")
        session.add(item)
        session.commit()
        session.refresh(item)
        bid = item.id
    results = search_fulltext(engine, "planning")
    assert [r["item_id"] for r in results] == [bid]


def test_search_returns_empty_for_no_match(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine)
    assert search_fulltext(engine, "zzzznonexistent") == []


def test_search_returns_empty_for_empty_query(tmp_path: Path) -> None:
    """A blank/whitespace query short-circuits to [] without touching the DB matchers."""
    engine = make_engine(tmp_path)
    add_item(engine)
    assert search_fulltext(engine, "") == []
    assert search_fulltext(engine, "   ") == []


def test_delete_content_removes_row_and_fts(tmp_path: Path) -> None:
    """delete_content removes the Content row and the FTS entry: get_fulltext is None
    and search_fulltext no longer matches a word that was in the body."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="uniqueword content body",
        source_url="u", content_type="text/html", status="ok",
    )
    delete_content(engine, item_id)
    assert get_fulltext(engine, item_id) is None
    assert search_fulltext(engine, "uniqueword") == []


def test_delete_content_is_idempotent(tmp_path: Path) -> None:
    """delete_content on an item with no stored content is a silent no-op."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    delete_content(engine, item_id)  # must not raise


def test_store_fulltext_sanitizes_lone_surrogates(tmp_path: Path) -> None:
    """Markdown containing an unpaired UTF-16 surrogate stores cleanly and reads back.

    Some fetched pages decode into lone surrogates (seen live on card 1155); SQLite's UTF-8
    encoder rejects them with UnicodeEncodeError, so store_fulltext must sanitize first.
    """
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    dirty = "ok \ud800 text"
    store_fulltext(
        engine, item_id=item_id, markdown=dirty,
        source_url="u", content_type="text/html", status="ok",
    )
    stored = get_fulltext(engine, item_id)
    assert stored is not None
    # The surrogate is replaced, the surrounding text survives, and the row is readable.
    assert stored["markdown"].startswith("ok ") and stored["markdown"].endswith(" text")
    assert "\ud800" not in stored["markdown"]
    assert stored["text_chars"] == len(stored["markdown"])


def test_store_fulltext_sanitizes_surrogates_in_error_string(tmp_path: Path) -> None:
    """A fetch error message carrying a lone surrogate must not crash the store."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(
        engine, item_id=item_id, markdown="", source_url="u",
        content_type="", status="failed", error="boom \udfff bad",
    )
    stored = get_fulltext(engine, item_id)
    assert stored["status"] == "failed"
    assert "\udfff" not in (stored["error"] or "")


def test_reindex_on_restore_drops_the_old_body(tmp_path: Path) -> None:
    """Re-storing replaces the FTS entry: old terms no longer match, new ones do."""
    engine = make_engine(tmp_path)
    item_id = add_item(engine)
    store_fulltext(engine, item_id=item_id, markdown="alphaunique text", source_url="u", content_type="text/html", status="ok")
    store_fulltext(engine, item_id=item_id, markdown="betareplaced text", source_url="u", content_type="text/html", status="ok")
    assert [r["item_id"] for r in search_fulltext(engine, "betareplaced")] == [item_id]
    assert search_fulltext(engine, "alphaunique") == []


def test_search_matches_title_even_when_item_has_stored_full_text(tmp_path: Path) -> None:
    """A card WITH stored content is still searched on its title.

    Regression for the YouTube card "BIO26 Healthcare special address": the body
    transcript never contains "bio" (FTS tokenizes "bio26" as one token), and the
    old fallback only searched title/summary for items with NO stored content --
    so a title match on a full-text card was invisible to search. This must fail
    before the fix (the item has stored content whose body does not contain "bio").
    """
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(
            source="youtube", external_id="bio26", url="https://youtube.com/watch?v=bio26",
            title="BIO26 Healthcare special address",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
    store_fulltext(
        engine, item_id=item_id,
        markdown="A transcript about healthcare policy and hospital funding.",
        source_url="u", content_type="text/html", status="ok",
    )
    results = search_fulltext(engine, "bio")
    assert [r["item_id"] for r in results] == [item_id]


def test_search_multi_term_matches_across_different_fields(tmp_path: Path) -> None:
    """Multi-term queries AND across terms, matching each term in any field.

    "bio youtube" needs "bio" in the title AND "youtube" in the url -- they need not
    both be in the same field.
    """
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(
            source="youtube", external_id="bio26", url="https://youtube.com/watch?v=bio26",
            title="BIO26 Healthcare special address",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
    store_fulltext(
        engine, item_id=item_id,
        markdown="A transcript about healthcare policy and hospital funding.",
        source_url="u", content_type="text/html", status="ok",
    )
    results = search_fulltext(engine, "bio youtube")
    assert [r["item_id"] for r in results] == [item_id]


def test_search_matches_origin_or_source_field(tmp_path: Path) -> None:
    """A term found only in origin/source (not title/body) still matches."""
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(
            source="rss", external_id="c", url="https://x.test/c",
            title="Weekly roundup", origin="BioPharma Dispatch",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
    results = search_fulltext(engine, "biopharma")
    assert [r["item_id"] for r in results] == [item_id]


def test_search_does_not_duplicate_item_matched_by_both_fts_and_metadata(tmp_path: Path) -> None:
    """An item whose stored body AND title both match a term is returned exactly once."""
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(
            source="rss", external_id="d", url="https://x.test/d",
            title="Uniqueterm roundup",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
    store_fulltext(
        engine, item_id=item_id,
        markdown="Body text mentions uniqueterm here too.",
        source_url="u", content_type="text/html", status="ok",
    )
    results = search_fulltext(engine, "uniqueterm")
    assert [r["item_id"] for r in results] == [item_id]
