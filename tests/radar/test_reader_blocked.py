"""Tests for the detector of block pages (error pages, bot walls, redirect stubs)."""

import pytest
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.models import ReaderDoc
from spyglass_service.radar.reader.blocked import BLOCKED_REASON, looks_blocked
from spyglass_service.radar.reader.build import ensure_reader_doc
from spyglass_service.radar.reader.http import Page

_LONG = ("The team measured how often the new method flagged polyps that clinicians missed, and "
         "compared the findings against three earlier studies from different hospitals. ") * 10


@pytest.mark.parametrize("title", [
    "403 Forbidden", "Access Denied", "Just a moment...", "Attention Required! | Cloudflare",
    "Verify you are human", "Please enable JavaScript", "Pardon Our Interruption",
])
def test_an_obvious_block_title_is_detected(title: str) -> None:
    """A block page announces itself in its title."""
    assert looks_blocked("Please wait while we check your browser.", title)


@pytest.mark.parametrize("text", [
    "Please enable JavaScript and cookies to continue.",
    "Access denied. You do not have permission to view this page.",
    "Verify you are human by completing the action below.",
    "You have been blocked. This website is using a security service to protect itself.",
    "We detected unusual traffic from your computer network. Are you a robot?",
    "Redirecting... Click here if you are not redirected automatically.",
    "403 Forbidden. nginx",
])
def test_a_short_text_with_a_block_phrase_is_detected(text: str) -> None:
    """Both conditions hold: the text is short and contains a block phrase."""
    assert looks_blocked(text, "")


def test_a_short_legitimate_post_is_not_a_block() -> None:
    """Short text without a block phrase is a real (small) post."""
    assert not looks_blocked("The model scored 91 percent on the held-out set. More soon.", "Quick note")
    assert not looks_blocked("Short post about forbidden fruit and denied claims.", "Fruit")


def test_a_long_article_mentioning_a_block_phrase_is_not_a_block() -> None:
    """A real article that discusses 'access denied' or 'enable JavaScript' stays readable."""
    text = _LONG + " The error page said Access denied and asked readers to enable JavaScript."
    assert not looks_blocked(text, "How block pages work")


def test_a_long_page_with_a_block_looking_title_but_real_text_is_kept() -> None:
    """A title alone does not condemn a page that has hundreds of words of real text."""
    assert not looks_blocked(_LONG * 5, "Access denied: a history of locks")


def test_an_empty_text_is_not_judged() -> None:
    """Nothing to judge; the caller handles empty pages separately."""
    assert not looks_blocked("", "")


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database."""
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def _build(engine, html: str) -> dict:
    """Build the reader document of a fresh item served `html`."""
    url = "https://news.example.org/x"
    with Session(engine) as session:
        item = Item(source="rss", external_id=url, title="A story", url=url, origin="Pub")
        session.add(item)
        session.commit()
        item_id = item.id
    page = Page(url=url, ok=True, body=html.encode(), content_type="text/html", status=200)
    return ensure_reader_doc(engine, Settings(), item_id, fetch=lambda u, headers=None: page)


def test_a_block_page_is_stored_as_failed_with_the_standard_reason(engine) -> None:
    """The error page is not stored as a readable document."""
    words = "Please enable JavaScript and cookies to continue. " + "Checking your browser. " * 3
    doc = _build(engine, f"<html><head><title>Just a moment...</title></head><body><p>{words}</p>"
                         "<p>Ray ID: 12345 performance and security by a provider for this site.</p>"
                         "<p>More filler words so that the page counts as an article of some length "
                         "for the minimum word rule to pass before the detector runs here.</p></body></html>")
    assert doc["status"] == "failed" and doc["error"] == BLOCKED_REASON and doc["html"] == ""
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc)).first().status == "failed"


def test_a_short_real_post_is_still_built(engine) -> None:
    """A short page without block phrases is a normal document."""
    body = ("<p>We shipped the new release today. It adds a faster loader, a clearer settings page and "
            "a fix for the crash that some of you reported last week. Thanks for the detailed reports "
            "and for your patience while we tracked the problem down across several platforms.</p>")
    doc = _build(engine, f"<html><head><title>Release notes</title></head><body><article>{body}</article></body></html>")
    assert doc["status"] == "ok" and "faster loader" in doc["html"]
