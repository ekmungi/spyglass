"""Tests for the importer: a page the reader brings in becomes (or replaces) an item's reader
document, without any network call."""

import socket
from types import SimpleNamespace

import fitz
import httpx
import pytest
from sqlmodel import Session, select

from spyglass_service.content_store import get_fulltext, store_fulltext
from spyglass_service.models import Item
from spyglass_service.radar import importer, netguard
from spyglass_service.radar.importer import ImportRefused, Incoming
from spyglass_service.radar.models import Assessment, ItemState, ReaderDoc, Signal
from spyglass_service.radar import from_you_store

from .test_sources_support import make_engine

URL = "https://news.example.com/2026/11/story"
BODY = " ".join(f"Sentence {n} explains the new results from the trial in plain words." for n in range(30))
PAGE = f"""<!DOCTYPE html><html><head><title>Trial results are in | News Example</title>
<meta property="og:site_name" content="News Example"></head>
<body><header><nav>Signed in as reader@example.com · My account · Log out</nav></header>
<article><h1>Trial results are in</h1><p>{BODY}</p><p>{BODY}</p>
<script>alert('x')</script><img src="/pic.jpg" onerror="alert(1)"></article>
<footer>Subscriber reader@example.com · Manage subscription</footer></body></html>"""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any lookup, connection or HTTP request during an import fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("the import path must not use the network")

    monkeypatch.setattr(netguard, "resolve", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    # The real network transport; the test client has its own, so it keeps working.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture()
def engine(tmp_path):
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def settings_for(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=tmp_path / "data")


def one(engine, model, item_id):
    with Session(engine) as session:
        return session.exec(select(model).where(model.item_id == item_id)).first()


def test_the_address_is_normalised_without_a_lookup() -> None:
    assert importer.validate_page_url(" https://News.Example.com/a?utm_source=x&id=2#top ") == \
        "https://news.example.com/a?id=2"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///C:/x", "http://localhost:7778/",
                                 "http://127.0.0.1/", "http://192.168.1.4/a", "http://[::1]/",
                                 "https://user:pw" "@news.example.com/", "http://intranet.local/x",
                                 "ftp://news.example.com/a", "", "http://0x7f.1/"])
def test_addresses_that_are_not_public_http_are_refused(url: str) -> None:
    with pytest.raises(ImportRefused):
        importer.validate_page_url(url)


def test_the_preview_is_plain_text_from_the_reader_extractor() -> None:
    preview = importer.preview_page(PAGE, URL)
    assert preview["title"] == "Trial results are in"
    assert preview["word_count"] > 200
    assert len(preview["excerpt"]) <= 600
    assert preview["excerpt"].startswith("Sentence 0 explains")
    assert "<" not in preview["excerpt"] and "alert" not in preview["excerpt"]
    assert "reader@example.com" not in preview["excerpt"]


def test_a_page_without_readable_text_previews_as_empty() -> None:
    preview = importer.preview_page("<html><body><script>x()</script></body></html>", URL)
    assert preview["word_count"] == 0 and preview["excerpt"] == ""


def test_importing_a_page_creates_a_from_you_item_with_a_clean_reader_document(engine, tmp_path) -> None:
    item_id = importer.import_page(engine, settings_for(tmp_path),
                                   Incoming(url=URL + "#comments", title="Trial results are in", html=PAGE))
    with Session(engine) as session:
        item = session.get(Item, item_id)
        assert item.url == URL and item.title == "Trial results are in" and item.source == "capture"
        signals = session.exec(select(Signal).where(Signal.item_id == item_id)).all()
    state = one(engine, ItemState, item_id)
    assert state.from_user is True and state.captured_via == "browser" and state.captured_at is not None
    assert [(s.kind, s.value) for s in signals] == [("capture", "browser")]
    doc = one(engine, ReaderDoc, item_id)
    assert (doc.kind, doc.status, doc.source_url) == ("article", "ok", URL)
    assert "Sentence 29 explains" in doc.html and doc.word_count > 200
    assert "<script" not in doc.html and "onerror" not in doc.html
    stored = get_fulltext(engine, item_id)
    assert stored["status"] == "ok" and "Sentence 0 explains" in stored["markdown"]
    assert one(engine, Assessment, item_id) is None


def test_only_the_article_body_is_kept_never_the_signed_in_page_chrome(engine, tmp_path) -> None:
    item_id = importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, html=PAGE))
    doc = one(engine, ReaderDoc, item_id)
    stored = get_fulltext(engine, item_id)
    for text in (doc.html, stored["markdown"]):
        assert "reader@example.com" not in text and "Log out" not in text


def test_importing_an_existing_item_replaces_its_failed_document_and_clears_its_judgement(engine, tmp_path) -> None:
    with Session(engine) as session:
        item = Item(source="rss", external_id="x1", title="Trial results are in", url=URL, origin="News")
        session.add(item)
        session.flush()
        item_id = item.id
        session.add(ReaderDoc(item_id=item_id, status="failed", error="HTTP 403", html=""))
        session.add(Assessment(item_id=item_id, stage="digest", score=12, tier="out", why="Old"))
        session.commit()
    store_fulltext(engine, item_id=item_id, markdown="Subscribe to read. " * 400, status="ok")
    got = importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, html=PAGE))
    assert got == item_id
    doc = one(engine, ReaderDoc, item_id)
    assert doc.status == "ok" and doc.error is None and "Sentence 3 explains" in doc.html
    assert one(engine, Assessment, item_id) is None
    assert "Subscribe to read" not in get_fulltext(engine, item_id)["markdown"]
    assert one(engine, ItemState, item_id).from_user is True


def test_an_item_without_a_title_takes_the_page_title(engine, tmp_path) -> None:
    with Session(engine) as session:
        session.add(Item(source="capture", external_id="cap-1", url=URL,
                         title="news.example.com (title not available)", origin="news.example.com"))
        session.commit()
    item_id = importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, html=PAGE))
    with Session(engine) as session:
        assert session.get(Item, item_id).title == "Trial results are in"


def test_a_page_with_no_readable_text_is_refused_before_anything_is_stored(engine, tmp_path) -> None:
    with pytest.raises(ImportRefused):
        importer.import_page(engine, settings_for(tmp_path),
                             Incoming(url=URL, html="<html><body><script>x()</script></body></html>"))
    with Session(engine) as session:
        assert session.exec(select(Item)).all() == []


def test_a_refused_address_stores_nothing(engine, tmp_path) -> None:
    with pytest.raises(ImportRefused):
        importer.import_page(engine, settings_for(tmp_path), Incoming(url="http://10.0.0.1/", html=PAGE))
    with Session(engine) as session:
        assert session.exec(select(Item)).all() == []


def test_pasted_plain_text_becomes_the_reader_document(engine, tmp_path) -> None:
    text = "Trial results are in\n\nThe first <paragraph> & more.\n\nThe second paragraph."
    item_id = importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, text=text, via="paste"))
    doc = one(engine, ReaderDoc, item_id)
    assert "The first &lt;paragraph&gt; &amp; more." in doc.html
    assert one(engine, ItemState, item_id).captured_via == "paste"
    with Session(engine) as session:
        assert session.get(Item, item_id).title == "Trial results are in"
    assert "The second paragraph." in get_fulltext(engine, item_id)["markdown"]


def test_pasted_html_source_goes_through_the_extractor(engine, tmp_path) -> None:
    item_id = importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, text=PAGE, via="paste"))
    doc = one(engine, ReaderDoc, item_id)
    assert "Sentence 5 explains" in doc.html and "<script" not in doc.html
    assert "reader@example.com" not in doc.html


def test_empty_pasted_text_is_refused(engine, tmp_path) -> None:
    with pytest.raises(ImportRefused):
        importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL, text="  \n "))


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_a_pdf_is_kept_for_the_viewer_and_its_text_stored(engine, tmp_path) -> None:
    settings = settings_for(tmp_path)
    data = make_pdf("Methods and results of the trial")
    item_id = importer.import_page(engine, settings, Incoming(url=URL, title="paper", pdf=data, via="file"))
    doc = one(engine, ReaderDoc, item_id)
    assert (doc.kind, doc.status, doc.alt_url) == ("pdf", "ok", URL)
    assert from_you_store.find(settings.data_dir, item_id)[0].read_bytes() == data
    assert not (settings.data_dir / "pdf_cache").exists()  # not the trimmed cache
    assert "Methods and results" in get_fulltext(engine, item_id)["markdown"]


def test_a_pdf_without_text_is_still_kept_for_the_viewer(engine, tmp_path) -> None:
    settings = settings_for(tmp_path)
    data = make_pdf("")
    item_id = importer.import_page(engine, settings, Incoming(url=URL, title="scan", pdf=data, via="file"))
    doc = one(engine, ReaderDoc, item_id)
    assert doc.kind == "pdf" and doc.word_count == 0
    assert from_you_store.find(settings.data_dir, item_id) is not None


def test_incoming_needs_exactly_one_kind_of_content(engine, tmp_path) -> None:
    with pytest.raises(ImportRefused):
        importer.import_page(engine, settings_for(tmp_path), Incoming(url=URL))
