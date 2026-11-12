"""Tests for the assessment's fallback fetch: it never requests a non-public address."""

import sys
import types

import pytest
from sqlmodel import Session

from spyglass_service import content_store
from spyglass_service.radar import assess

from .test_assess_support import add_item, make_engine, make_settings


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _set_url(engine, item_id: int, url: str) -> None:
    """Point an item at `url`."""
    with Session(engine) as session:
        item = session.get(assess.Item, item_id)
        item.url = url
        session.add(item)
        session.commit()


def _broken_reader(monkeypatch) -> None:
    """Make the reader builder raise so the fallback fetch runs."""
    module = types.ModuleType("spyglass_service.radar.reader.build")

    def broken(*_args, **_kwargs):
        """A reader build that raises."""
        raise RuntimeError("boom")

    module.ensure_reader_doc = broken
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", module)


def test_fallback_fetch_refuses_a_private_address(engine, tmp_path, monkeypatch) -> None:
    """The fallback never requests a private address; a failed row is stored instead."""
    item_id = add_item(engine)
    _set_url(engine, item_id, "http://192.168.1.5/admin")
    _broken_reader(monkeypatch)
    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext",
                        lambda *a, **k: pytest.fail("a private address must not be fetched"))
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    stored = content_store.get_fulltext(engine, item_id)
    assert stored["status"] == "failed" and stored["error"]
    assert not stored["markdown"]


def test_fallback_fetch_discards_text_from_a_private_final_address(
        engine, tmp_path, monkeypatch) -> None:
    """Text whose final address is private is not stored."""
    item_id = add_item(engine)
    _broken_reader(monkeypatch)
    monkeypatch.setattr(
        "spyglass_service.documents.fetch_fulltext",
        lambda url, **_k: {"markdown": "secret page", "status": "ok",
                           "source_url": "http://127.0.0.1:8080/"})
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    stored = content_store.get_fulltext(engine, item_id)
    assert stored["status"] == "failed" and "secret" not in (stored["markdown"] or "")


def test_fallback_fetch_uses_a_guarded_client_and_guarded_rungs(engine, tmp_path, monkeypatch) -> None:
    """The ladder gets a client that checks every hop and a curl rung that follows by hand."""
    from spyglass_service import fetch_rungs
    from spyglass_service.radar import netguard

    item_id = add_item(engine)
    _set_url(engine, item_id, "https://example.org/article")
    seen: dict = {}

    def fake_fetch(url, **kwargs):
        """Record what the engine was given, and try the client on a private address."""
        seen.update(kwargs)
        try:
            kwargs["client"].get("http://127.0.0.1:7778/")
        except netguard.BlockedAddress:
            seen["refused"] = True
        return {"markdown": "text", "status": "ok", "source_url": url}

    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext", fake_fetch)
    from spyglass_service.radar.assess_fetch import plain_fetch

    plain_fetch(engine, make_settings(tmp_path), item_id)
    assert seen.get("refused") is True
    first_rung = seen["acquire_rungs"][0]
    assert first_rung is not fetch_rungs._acquire_curl_cffi and first_rung.tier == "T1"
