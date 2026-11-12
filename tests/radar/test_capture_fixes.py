"""Regression tests for captures: a link the radar already had becomes "From you" again and is
re-judged, captured items of switched-off feeds are kept, hidden local addresses are refused,
and the title fetch is size-capped and decodes the page's own character set."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from spyglass_service.models import Feed, Item
from spyglass_service.radar import capture_title
from spyglass_service.radar.assess import store_assessment
from spyglass_service.radar.brief.compose import compose_brief
from spyglass_service.radar.capture import (
    CaptureError,
    capture_url,
    mark_raindrop_captures,
    validate_capture_url,
)
from spyglass_service.radar.models import Assessment, ItemState
from spyglass_service.radar.pipeline import run_pipeline

from . import test_assess_support as assess_support
from .test_brief_seed import NOW, add_item, make_engine

SETTINGS = SimpleNamespace(radar_timezone="UTC", radar_writer_model="m", openrouter_api_key=None)
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731 -- a resolver stub


def _llm(_messages, _schema):
    """A writer model that always answers."""
    return {"opening": "x"}


def _from_you(doc: dict) -> set[int]:
    """Item ids in the brief's From you section."""
    return {st["item_id"] for sec in doc["sections"] if sec["key"] == "from_you"
            for st in sec["stories"]}


def _state(engine, item_id: int) -> ItemState:
    """The item's reader state."""
    with Session(engine) as session:
        return session.exec(select(ItemState).where(ItemState.item_id == item_id)).one()


def test_capturing_a_link_the_radar_already_had_puts_it_in_from_you(tmp_path) -> None:
    """The reviewer's case: a feed item judged out two days ago, captured today."""
    engine = make_engine(tmp_path)
    try:
        old = add_item(engine, "Article the feed already had", score=20, tier="out",
                       age_hours=40, url="https://news.example.com/story")
        compose_brief(engine, SETTINGS, None, llm=_llm,
                      now=(NOW - timedelta(days=1)).replace(hour=6, minute=30))
        got = capture_url(engine, None, "https://news.example.com/story", via="slack",
                          title_fetch=lambda u: "t", resolver=PUBLIC)
        assert got == old and _state(engine, old).captured_at is not None
        with Session(engine) as session:
            row = session.exec(select(Assessment).where(Assessment.item_id == old)).one()
        # Sent in by the reader: new evidence, so it is digested again and no longer "out".
        assert row.stage == "triage" and row.tier != "out" and row.digest_attempts == 0
        # The capture is stamped with the real clock, so the brief must be composed after it: a fixed
        # "now" would be earlier than the capture on any day this test runs after noon UTC.
        doc = compose_brief(engine, SETTINGS, None, llm=_llm, now=datetime.now(UTC) + timedelta(minutes=1))
        assert old in _from_you(doc)
    finally:
        engine.dispose()


def test_capture_time_is_recorded_on_every_capture(tmp_path) -> None:
    """A new capture, a repeated capture and a Raindrop bookmark all set captured_at."""
    engine = make_engine(tmp_path)
    try:
        first = capture_url(engine, None, "https://example.com/a", title_fetch=lambda u: "A",
                            resolver=PUBLIC)
        stamp = _state(engine, first).captured_at
        capture_url(engine, None, "https://example.com/a", title_fetch=lambda u: "A",
                    resolver=PUBLIC)
        assert stamp is not None and _state(engine, first).captured_at >= stamp
        bookmark = add_item(engine, "Bookmark", score=None, source="raindrop", age_hours=2)
        assert mark_raindrop_captures(engine) == 1
        with Session(engine) as session:
            fetched = session.get(Item, bookmark).fetched_at
        assert _state(engine, bookmark).captured_at == fetched
    finally:
        engine.dispose()


def test_a_reader_item_from_a_switched_off_feed_is_kept_in_the_brief(tmp_path) -> None:
    """Switching a feed off never hides what the reader sent in."""
    engine = make_engine(tmp_path)
    try:
        item_id = add_item(engine, "From an off feed", score=None, from_user=True, age_hours=2)
        with Session(engine) as session:
            session.add(Feed(feed_url="https://off.test/feed", name="Off", kind="rss",
                             enabled=False, added_via="manual"))
            item = session.get(Item, item_id)
            item.feed_url = "https://off.test/feed"
            session.add(item)
            session.commit()
        assert item_id in _from_you(compose_brief(engine, SETTINGS, None, llm=_llm, now=NOW))
    finally:
        engine.dispose()


def test_an_old_item_captured_today_is_judged_by_the_pipeline(tmp_path) -> None:
    """The pipeline's window for reader items follows the capture time, not the fetch time."""
    engine = assess_support.make_engine(tmp_path)
    try:
        item_id = assess_support.add_item(engine, "Old article", age_hours=24 * 45)
        with Session(engine) as session:
            url = session.get(Item, item_id).url
        assert capture_url(engine, None, url, title_fetch=lambda u: "t", resolver=PUBLIC) == item_id
        llm = assess_support.FakeLlm()
        run_pipeline(engine, assess_support.make_settings(tmp_path), None, llm=llm,
                     fetch=lambda _i: None)
        assert llm.count("triage") == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad", [
    "http://127.1:7778/", "http://0177.0.0.1/", "http://2130706433/", "http://localhost./",
    "http://0x7f.1/", "http://100.64.1.1/", "http://10.1/x", "http://[::ffff:127.0.0.1]/",
])
def test_hidden_forms_of_local_addresses_are_refused(bad: str) -> None:
    """Short, octal, decimal and hex forms of local addresses, and carrier-grade NAT."""
    with pytest.raises(CaptureError):
        validate_capture_url(bad)


def test_a_name_resolving_to_carrier_grade_nat_is_refused(tmp_path) -> None:
    """The final decision is netguard's, which knows the ranges the standard library misses."""
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(CaptureError):
            capture_url(engine, None, "https://cgnat.example.com/x",
                        resolver=lambda host: ["100.64.0.5"])
    finally:
        engine.dispose()


def test_a_title_that_cannot_be_fetched_reads_as_the_host(tmp_path) -> None:
    """The brief never shows a bare address as a headline."""
    engine = make_engine(tmp_path)
    try:
        item_id = capture_url(engine, None, "https://www.example.com/a/b?x=1",
                              title_fetch=lambda u: None, resolver=PUBLIC)
        with Session(engine) as session:
            assert session.get(Item, item_id).title == "www.example.com (title not available)"
    finally:
        engine.dispose()


def _client_for(handler):
    """A client factory whose requests go to `handler` instead of the network."""
    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


def test_title_fetch_decodes_the_declared_character_set() -> None:
    """A windows-1252 page with a curly apostrophe is read without a replacement character."""
    page = "<html><head><meta charset=\"windows-1252\"><title>Building Meta’s GenAI " \
           "Infrastructure</title></head><body>x</body></html>"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=page.encode("cp1252"))

    title = capture_title.fetch_title("https://example.com/p", client_factory=_client_for(handler),
                                      resolver=PUBLIC)
    assert title == "Building Meta’s GenAI Infrastructure"
    assert "�" not in title


def test_title_fetch_reads_at_most_512_kilobytes() -> None:
    """A huge page is not read to the end: a title beyond the cap is never seen."""
    body = b"<html><head>" + b" " * (600 * 1024) + b"<title>Too late</title></head></html>"
    sent = {"bytes": 0}

    def stream():
        for start in range(0, len(body), 64 * 1024):
            chunk = body[start:start + 64 * 1024]
            sent["bytes"] += len(chunk)
            yield chunk

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=stream())

    title = capture_title.fetch_title("https://example.com/big",
                                      client_factory=_client_for(handler), resolver=PUBLIC)
    assert title is None and sent["bytes"] <= capture_title.MAX_TITLE_BYTES + 64 * 1024


def test_title_fetch_refuses_a_redirect_to_a_private_address() -> None:
    """Each hop is checked with netguard before it is requested."""
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://100.64.0.1/admin"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<title>internal</title>")

    title = capture_title.fetch_title("https://example.com/r", client_factory=_client_for(handler),
                                      resolver=PUBLIC)
    assert title is None and seen == ["https://example.com/r"]


def test_old_assessment_of_a_recaptured_digest_is_lifted(tmp_path) -> None:
    """A digested item judged out is sent back to be digested when the reader captures it."""
    engine = make_engine(tmp_path)
    try:
        item_id = add_item(engine, "Judged out", score=10, tier="out",
                           url="https://example.com/out")
        store_assessment(engine, item_id, {"digest_attempts": 2})
        capture_url(engine, None, "https://example.com/out", title_fetch=lambda u: "t",
                    resolver=PUBLIC)
        with Session(engine) as session:
            row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).one()
        assert (row.stage, row.digest_attempts) == ("triage", 0) and row.tier == "notable"
    finally:
        engine.dispose()
