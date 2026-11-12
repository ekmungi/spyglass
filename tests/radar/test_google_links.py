"""Tests for resolving Google News redirect links on items before their reader page is built."""

import sys
import types

import pytest
from sqlmodel import Session

from spyglass_service.radar import assess
from spyglass_service.radar.sources import google_links
from spyglass_service.radar.sources.google_links import resolve_item_url

from .test_assess_support import add_item, make_engine, make_settings

GOOGLE = "https://news.google.com/rss/articles/CBMiabc?oc=5"


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch) -> None:
    """The politeness pause is not needed with a fake decoder."""
    monkeypatch.setattr(google_links.time, "sleep", lambda _s: None)


def _set_url(engine, item_id: int, url: str) -> None:
    """Point an item at `url`."""
    with Session(engine) as session:
        item = session.get(google_links.Item, item_id)
        item.url = url
        session.add(item)
        session.commit()


def _url(engine, item_id: int) -> str:
    """The stored address of an item."""
    with Session(engine) as session:
        return session.get(google_links.Item, item_id).url


def test_a_google_link_is_replaced_by_the_publisher_address(engine) -> None:
    item_id = add_item(engine)
    _set_url(engine, item_id, GOOGLE)
    seen: list[list[str]] = []

    def decode(links: list[str]) -> list[str | None]:
        """A decoder that resolves every link to the same article."""
        seen.append(links)
        return ["https://publisher.example.com/story"]

    assert resolve_item_url(engine, item_id, decode=decode) is True
    assert _url(engine, item_id) == "https://publisher.example.com/story"
    assert seen == [[GOOGLE]]


def test_other_addresses_are_left_alone_without_calling_the_decoder(engine) -> None:
    item_id = add_item(engine)
    before = _url(engine, item_id)
    assert resolve_item_url(engine, item_id, decode=lambda _l: pytest.fail("no call")) is False
    assert _url(engine, item_id) == before
    assert resolve_item_url(engine, 99999, decode=lambda _l: pytest.fail("no call")) is False


@pytest.mark.parametrize("result", [None, "http://10.0.0.5/admin", "ftp://x.example/a", ""])
def test_a_failed_or_unsafe_result_keeps_the_old_address(engine, result) -> None:
    item_id = add_item(engine)
    _set_url(engine, item_id, GOOGLE)
    assert resolve_item_url(engine, item_id, decode=lambda _l: [result]) is False
    assert _url(engine, item_id) == GOOGLE


def test_a_decoder_that_raises_keeps_the_old_address(engine) -> None:
    item_id = add_item(engine)
    _set_url(engine, item_id, GOOGLE)

    def broken(_links: list[str]) -> list[str | None]:
        """A decoder that blows up."""
        raise RuntimeError("down")

    assert resolve_item_url(engine, item_id, decode=broken) is False
    assert _url(engine, item_id) == GOOGLE


def test_calls_are_spaced_by_the_decoder_interval(engine, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(google_links.time, "sleep", sleeps.append)
    monkeypatch.setattr(google_links, "_last_call", [google_links.time.monotonic()])
    item_id = add_item(engine)
    _set_url(engine, item_id, GOOGLE)
    resolve_item_url(engine, item_id, decode=lambda _l: [None])
    assert sleeps and 0 < sleeps[0] <= google_links.DECODE_INTERVAL


def test_the_digest_fetch_resolves_the_link_before_building_the_reader_page(
        engine, tmp_path, monkeypatch) -> None:
    item_id = add_item(engine)
    _set_url(engine, item_id, GOOGLE)
    monkeypatch.setattr("spyglass_service.radar.sources.news_search.decode_google_urls",
                        lambda links: ["https://publisher.example.com/story"])
    seen: list[str] = []
    module = types.ModuleType("spyglass_service.radar.reader.build")

    def build(eng, settings, i):
        """Record which address the reader would fetch."""
        seen.append(_url(eng, i))

    module.ensure_reader_doc = build
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", module)
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    assert seen == ["https://publisher.example.com/story"]
