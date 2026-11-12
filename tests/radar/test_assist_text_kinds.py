# ruff: noqa: F811
"""Tests for what the assistant is told about the text it has: full, preview, excerpt or summary only."""

from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar.assist import context
from spyglass_service.radar.models import ReaderDoc

from .test_assist_support import add_item, clean_assist_env, db  # noqa: F401

SUMMARY = "The company released a robot that cut tissue with sub-millimetre precision in trials."


def _set_summary(db, item_id: int, summary: str) -> None:
    """Store the feed's own summary on an item."""
    with Session(db) as session:
        session.get(Item, item_id).summary = f"<p>{summary}</p>"
        session.commit()


def _mark_reader(db, item_id: int, status: str) -> None:
    """Give an item a stored reader document with the given status."""
    with Session(db) as session:
        session.add(ReaderDoc(item_id=item_id, kind="article", html="<p>x</p>", status=status, word_count=40))
        session.commit()


def test_text_kind_by_length_status_and_summary() -> None:
    assert context.text_kind(0, True, None) == "summary"
    assert context.text_kind(0, False, None) == "none"
    assert context.text_kind(900, True, "partial") == "preview"
    assert context.text_kind(40, True, "ok") == "short"
    assert context.text_kind(900, False, "ok") == "full"


def test_item_without_text_gets_the_feed_summary_and_says_it_is_all_there_is(db):
    item_id = add_item(db, text=None)
    _set_summary(db, item_id, SUMMARY)
    system = context.build_system(db, item_id=item_id)
    assert f"Summary from the feed: {SUMMARY}" in system
    assert "all you have is the feed's own summary" in system
    assert "No full text is stored" in system and "<p>" not in system


def test_short_text_is_labelled_an_excerpt_and_still_carries_the_summary(db):
    item_id = add_item(db, text="Only a few words stored here.")
    _set_summary(db, item_id, SUMMARY)
    system = context.build_system(db, item_id=item_id)
    assert "may be only an excerpt" in system and SUMMARY in system
    assert "Stored text:\nOnly a few words stored here." in system


def test_full_text_is_labelled_full_and_the_summary_is_left_out(db):
    item_id = add_item(db, text="Full sentence of the article. " * 200)
    _set_summary(db, item_id, SUMMARY)
    system = context.build_system(db, item_id=item_id)
    assert "Text supplied: the full article text." in system
    assert "Full text:\nFull sentence" in system and SUMMARY not in system


def test_paywalled_preview_is_labelled_a_preview(db):
    item_id = add_item(db, text="Preview paragraph of the article. " * 20)
    _mark_reader(db, item_id, "partial")
    system = context.build_system(db, item_id=item_id)
    assert "only a PREVIEW" in system and "limits the full article to subscribers" in system


def test_item_with_neither_text_nor_summary_says_so(db):
    item_id = add_item(db, text=None)
    assert "No article text and no summary are stored" in context.build_system(db, item_id=item_id)


def test_cut_text_says_what_is_shown_and_warns_against_claiming_absence(db, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 2_000)
    item_id = add_item(db, text="Alpha sentence goes here. " * 400)
    system = context.build_system(db, item_id=item_id)
    assert "is the beginning of the article" in system and "selected passages" in system
    assert "Do not say that a section or a topic is missing" in system


def test_text_that_fits_has_no_omission_marker(db):
    item_id = add_item(db, text="Alpha sentence goes here. " * 300)
    system = context.build_system(db, item_id=item_id)
    assert "beginning of the article" not in system and "selected passages" not in system
