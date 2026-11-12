"""Tests for link capture: validation, dedupe, from-you marking and Raindrop marking."""

import pytest
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.ingest import store_items
from spyglass_service.models import Card
from spyglass_service.radar.capture import (
    CaptureError,
    capture_url,
    mark_raindrop_captures,
    validate_capture_url,
)
from spyglass_service.radar.models import ItemState, Signal

from .test_sources_support import all_items, make_engine, make_settings

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731 -- a resolver stub


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/x", "", "   ",
    "http://localhost/admin", "http://127.0.0.1:7777/api", "http://[::1]/x",
    "http://10.0.0.5/x", "http://192.168.1.1/", "http://169.254.169.254/latest",
    "http://printer.local/", "http://intranet/wiki", "http://user:pw@example.com/",
    "https://" + "a" * 2100 + ".com",
])
def test_validate_rejects_unsafe_or_unusable_links(bad: str) -> None:
    with pytest.raises(CaptureError):
        validate_capture_url(bad)


def test_validate_normalises_case_fragment_port_and_tracking() -> None:
    url = "HTTPS://Example.COM:443/Path?utm_source=x&keep=1&fbclid=abc#section"
    assert validate_capture_url(url) == "https://example.com/Path?keep=1"
    assert validate_capture_url("http://example.com") == "http://example.com/"


def test_capture_creates_a_from_you_item_with_card_state_and_signal(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        item_id = capture_url(engine, make_settings(), "https://example.com/a?utm_medium=x",
                              note="read this", via="slack",
                              title_fetch=lambda u: "A Title", resolver=PUBLIC)
        (item,) = all_items(engine, "capture")
        assert item.id == item_id and item.title == "A Title"
        assert item.url == "https://example.com/a" and item.origin == "example.com"
        with Session(engine) as session:
            state = session.exec(select(ItemState)).one()
            assert (state.from_user, state.captured_via, state.user_note) == (
                True, "slack", "read this")
            assert session.exec(select(Signal).where(Signal.kind == "capture")).one().value == "slack"
            assert session.exec(select(Card).where(Card.item_id == item_id)).first() is not None
    finally:
        engine.dispose()


def test_capture_never_fails_when_the_title_fetch_fails(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        def boom(url: str) -> str:
            raise OSError("timeout")

        capture_url(engine, make_settings(), "https://example.com/slow", title_fetch=boom,
                    resolver=PUBLIC)
        assert all_items(engine, "capture")[0].title == "example.com (title not available)"
    finally:
        engine.dispose()


def test_capture_dedupes_against_existing_items_and_marks_them(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        store_items(engine, [CollectedItem(source="rss", external_id="e1", title="Existing",
                                           url="https://example.com/post/")])
        first = capture_url(engine, make_settings(), "https://example.com/post/#top",
                            note="n1", via="email", title_fetch=lambda u: "x", resolver=PUBLIC)
        again = capture_url(engine, make_settings(), "https://example.com/post",
                            via="manual", title_fetch=lambda u: "x", resolver=PUBLIC)
        assert first == again
        assert all_items(engine, "capture") == []  # nothing new was created
        with Session(engine) as session:
            state = session.exec(select(ItemState)).one()
            assert state.from_user and state.captured_via == "email"  # first channel kept
            assert state.user_note == "n1"
    finally:
        engine.dispose()


def test_capture_same_link_twice_creates_one_item(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        a = capture_url(engine, make_settings(), "https://example.com/x",
                        title_fetch=lambda u: "T", resolver=PUBLIC)
        b = capture_url(engine, make_settings(), "https://EXAMPLE.com/x#frag",
                        title_fetch=lambda u: "T", resolver=PUBLIC)
        assert a == b and len(all_items(engine, "capture")) == 1
    finally:
        engine.dispose()


def test_capture_matches_the_arxiv_abstract_and_pdf_forms(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        store_items(engine, [CollectedItem(source="rss", external_id="a", title="Paper",
                                           url="https://arxiv.org/pdf/2611.08379")])
        capture_url(engine, make_settings(), "https://arxiv.org/abs/2611.08379",
                    title_fetch=lambda u: "x", resolver=PUBLIC)
        assert all_items(engine, "capture") == []
    finally:
        engine.dispose()


def test_capture_rejects_a_public_name_that_resolves_privately(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(CaptureError):
            capture_url(engine, make_settings(), "https://rebind.example.com/x",
                        resolver=lambda host: ["127.0.0.1"])
        assert all_items(engine) == []
        # An unresolvable name is kept (offline captures still work).
        def offline(host: str) -> list[str]:
            raise OSError("no dns")

        capture_url(engine, make_settings(), "https://offline.example.com/x",
                    title_fetch=lambda u: None, resolver=offline)
        assert len(all_items(engine, "capture")) == 1
    finally:
        engine.dispose()


def test_mark_raindrop_captures_marks_once(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        store_items(engine, [
            CollectedItem(source="raindrop", external_id="1", title="Bookmark",
                          url="https://example.com/1"),
            CollectedItem(source="rss", external_id="2", title="Feed", url="https://example.com/2"),
        ])
        assert mark_raindrop_captures(engine) == 1
        assert mark_raindrop_captures(engine) == 0
        with Session(engine) as session:
            state = session.exec(select(ItemState)).one()
            assert state.from_user and state.captured_via == "raindrop"
    finally:
        engine.dispose()
