"""Tests for ensure_reader_doc: routing, storage, text for search, caching and failure handling."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.content_store import get_fulltext, store_fulltext
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.models import ItemState, ReaderDoc
from spyglass_service.radar.reader import http as http_mod
from spyglass_service.radar.reader.build import ensure_reader_doc
from spyglass_service.radar.reader.http import Page
from spyglass_service.radar.reader.redirects import RedirectOutcome
from spyglass_service.radar.reader.text import markdown_to_html, plain_abstract, plain_text

_PARA = ("Researchers built a new tool that reads clinical images quickly and they checked it against "
         "several hospital datasets collected in three countries over two years. ")
ARTICLE = (f"<html><head><title>Story</title><meta property='og:title' content='Story'></head><body>"
           f"<article><h1>Story</h1><p>{_PARA * 4}</p><h2>Method</h2><p>{_PARA * 3}</p></article></body></html>")


BIG_ARTICLE = ("<html><head><title>Story</title></head><body><article><h1>Story</h1>"
               + "".join(f"<p>{_PARA}</p>" for _ in range(70)) + "</article></body></html>")


@pytest.fixture()
def engine(tmp_path):
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def _item(engine, url: str, *, title: str = "An item", summary: str | None = None) -> int:
    with Session(engine) as session:
        item = Item(source="rss", external_id=url, title=title, url=url, summary=summary, origin="Pub")
        session.add(item)
        session.commit()
        return item.id


class FakeFetch:
    """A fetcher serving canned pages by URL and counting calls."""

    def __init__(self, pages: dict[str, Page]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str, headers=None) -> Page:
        self.calls.append(url)
        return self.pages.get(url) or Page(url=url, ok=False, status=404, error="HTTP 404")


def _html_page(url: str, html: str) -> Page:
    return Page(url=url, ok=True, body=html.encode(), content_type="text/html", status=200)


def test_article_is_built_stored_and_its_text_saved(engine) -> None:
    url = "https://news.example.org/story"
    item_id = _item(engine, url)
    fetch = FakeFetch({url: _html_page(url, ARTICLE)})
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["kind"] == "article" and doc["status"] == "ok"
    assert "<h2>Method</h2>" in doc["html"] and doc["word_count"] > 100
    assert doc["source_url"] == url
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first().status == "ok"
    stored = get_fulltext(engine, item_id)
    assert stored["status"] == "ok" and "Researchers built a new tool" in stored["markdown"]
    assert "<p>" not in stored["markdown"]


def test_existing_ok_doc_is_returned_without_refetching_unless_forced(engine) -> None:
    url = "https://news.example.org/story"
    item_id = _item(engine, url)
    fetch = FakeFetch({url: _html_page(url, ARTICLE)})
    ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert fetch.calls == [url]
    ensure_reader_doc(engine, Settings(), item_id, force=True, fetch=fetch)
    assert fetch.calls == [url, url]
    with Session(engine) as session:
        assert len(session.exec(select(ReaderDoc)).all()) == 1


def test_fetch_failure_is_stored_not_raised_and_retried_after_an_hour(engine) -> None:
    url = "https://dead.example.org/x"
    item_id = _item(engine, url)
    fetch = FakeFetch({})
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["status"] == "failed" and doc["error"] and doc["html"] == ""
    ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert len(fetch.calls) == 1  # inside the retry window
    with Session(engine) as session:
        row = session.exec(select(ReaderDoc)).first()
        row.fetched_at = datetime.now(UTC) - timedelta(hours=2)
        session.add(row)
        session.commit()
    fetch.pages[url] = _html_page(url, ARTICLE)
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["status"] == "ok" and len(fetch.calls) == 2


def test_failed_doc_stores_no_text(engine) -> None:
    item_id = _item(engine, "https://dead.example.org/x")
    ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({}))
    assert get_fulltext(engine, item_id) is None


def test_a_passing_network_failure_is_shown_but_not_stored(engine) -> None:
    """A momentary network problem is retried on the next open, not held for an hour."""
    url = "https://flaky.example.org/x"
    item_id = _item(engine, url)
    down = Page(url=url, ok=False, error="The site could not be reached.", transient=True)
    fetch = FakeFetch({url: down})
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["status"] == "failed" and "reached" in doc["error"]
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc)).first() is None
    fetch.pages[url] = _html_page(url, ARTICLE)
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["status"] == "ok" and len(fetch.calls) == 2  # tried again straight away


def test_a_lasting_failure_is_still_stored(engine) -> None:
    """A page that answered with an error (not a passing network problem) is stored and held."""
    url = "https://gone.example.org/x"
    item_id = _item(engine, url)
    fetch = FakeFetch({url: Page(url=url, ok=False, status=404, error="HTTP 404")})
    ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc)).first().status == "failed"


def test_stub_page_is_a_failure_with_a_reason(engine) -> None:
    url = "https://stub.example.org/x"
    item_id = _item(engine, url)
    doc = ensure_reader_doc(engine, Settings(), item_id,
                            fetch=FakeFetch({url: _html_page(url, "<html><body><p>Please log in.</p></body></html>")}))
    assert doc["status"] == "failed" and "readable" in doc["error"]


def test_unexpected_exception_in_a_builder_becomes_a_failed_doc(engine) -> None:
    item_id = _item(engine, "https://news.example.org/story")

    def boom(url: str, headers=None) -> Page:
        raise RuntimeError("kaput")

    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=boom)
    assert doc["status"] == "failed" and "kaput" not in doc["error"]


def test_unknown_item_raises_lookup_error(engine) -> None:
    with pytest.raises(LookupError):
        ensure_reader_doc(engine, Settings(), 999, fetch=FakeFetch({}))


def test_email_doc_is_returned_as_is_even_when_forced(engine) -> None:
    item_id = _item(engine, "https://mail.example.org/m")
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="email", html="<p>hello</p>", status="ok"))
        session.commit()
    fetch = FakeFetch({})
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True, fetch=fetch)
    assert doc["kind"] == "email" and doc["html"] == "<p>hello</p>" and fetch.calls == []


def test_longer_stored_text_is_not_overwritten(engine) -> None:
    url = "https://news.example.org/story"
    item_id = _item(engine, url)
    store_fulltext(engine, item_id=item_id, markdown="X" * 50000, source_url=url)
    ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({url: _html_page(url, ARTICLE)}))
    assert get_fulltext(engine, item_id)["markdown"] == "X" * 50000


def test_shorter_stored_text_is_replaced(engine) -> None:
    url = "https://news.example.org/story"
    item_id = _item(engine, url)
    store_fulltext(engine, item_id=item_id, markdown="short snippet", source_url=url)
    ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({url: _html_page(url, ARTICLE)}))
    assert "Researchers built a new tool" in get_fulltext(engine, item_id)["markdown"]


def test_arxiv_paper_with_html_edition(engine) -> None:
    item_id = _item(engine, "https://arxiv.org/abs/2401.00001v1", title="Paper")
    words = "evidence retrieval differential reasoning model benchmark accuracy " * 30
    edition = (f'<html><body><article class="ltx_document"><h1 class="ltx_title_document">Paper</h1>'
               f'<div class="ltx_abstract"><p>{words}</p></div><p>Equation '
               f'<math alttext="x^2"><msup><mi>x</mi><mn>2</mn></msup></math> inline.</p></article></body></html>')
    fetch = FakeFetch({"https://arxiv.org/html/2401.00001v1": _html_page("https://arxiv.org/html/2401.00001v1", edition)})
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=fetch)
    assert doc["kind"] == "paper" and "<math" in doc["html"]
    assert doc["alt_url"] == "https://arxiv.org/pdf/2401.00001v1"
    assert "x^2" in get_fulltext(engine, item_id)["markdown"]


def test_arxiv_paper_without_html_edition_is_a_pdf_doc_with_abstract(engine) -> None:
    summary = "arXiv:2401.00002v1 Announce Type: new Abstract: We study retrieval of evidence."
    item_id = _item(engine, "https://arxiv.org/abs/2401.00002v1", title="Paper", summary=summary)
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({}))
    assert doc["kind"] == "pdf" and doc["status"] == "ok"
    assert doc["alt_url"] == "https://arxiv.org/pdf/2401.00002v1"
    assert "We study retrieval of evidence." in doc["html"] and "Announce Type" not in doc["html"]


def test_youtube_item_becomes_a_video_doc(engine) -> None:
    item_id = _item(engine, "https://www.youtube.com/watch?v=N5YLi8Ar3Wg", title="A talk")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({}),
                            transcriber=lambda vid: "Hello everyone. Welcome to the talk.")
    assert doc["kind"] == "video" and "Welcome to the talk." in doc["html"]
    assert doc["alt_url"].endswith("N5YLi8Ar3Wg")
    assert "Welcome to the talk." in get_fulltext(engine, item_id)["markdown"]


def test_youtube_without_transcript_is_ok_with_player(engine) -> None:
    item_id = _item(engine, "https://youtu.be/N5YLi8Ar3Wg")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({}), transcriber=lambda vid: None)
    assert doc["status"] == "ok" and "No transcript" in doc["html"] and doc["alt_url"]


def test_github_repo_uses_the_api_and_falls_back_when_limited(engine) -> None:
    url = "https://github.com/owner/repo"
    readme = f"<article><p>{_PARA * 3}</p></article>"
    item_id = _item(engine, url)
    ok = FakeFetch({"https://api.github.com/repos/owner/repo/readme": _html_page("x", readme)})
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=ok)
    assert doc["site"] == "GitHub" and "Researchers built" in doc["html"]

    other = _item(engine, "https://github.com/owner/other")
    limited = FakeFetch({
        "https://api.github.com/repos/owner/other/readme": Page(url="x", ok=False, status=403, error="HTTP 403"),
        "https://github.com/owner/other": _html_page("https://github.com/owner/other", ARTICLE),
    })
    doc = ensure_reader_doc(engine, Settings(), other, fetch=limited)
    assert doc["kind"] == "article" and doc["status"] == "ok"
    assert limited.calls == ["https://api.github.com/repos/owner/other/readme", "https://github.com/owner/other"]


def test_plain_pdf_url_becomes_a_pdf_doc_with_extracted_text(engine) -> None:
    import fitz

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "The quarterly device report says hello.")
    data = pdf.tobytes()
    pdf.close()
    url = "https://docs.example.org/report.pdf"
    item_id = _item(engine, url, title="Report")
    page = Page(url=url, ok=True, body=data, content_type="application/pdf", status=200)
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({url: page}))
    assert doc["kind"] == "pdf" and doc["alt_url"] == url
    assert "quarterly device report" in get_fulltext(engine, item_id)["markdown"]


def test_markdown_page_from_a_fetch_rung_is_converted(engine) -> None:
    url = "https://blocked.example.org/post"
    item_id = _item(engine, url)
    md = "# Heading\n\n" + (_PARA * 4) + "\n\n- point one\n- point two\n\n![pic](/a.png)\n"
    page = Page(url=url, ok=True, body=md, content_type="text/markdown", is_markdown=True)
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=FakeFetch({url: page}))
    assert doc["status"] == "ok" and "<h1>Heading</h1>" in doc["html"] and "<li>point one</li>" in doc["html"]
    assert 'src="https://blocked.example.org/a.png"' in doc["html"]


# --- text helpers ------------------------------------------------------------------------------


def test_plain_text_separates_blocks_and_keeps_math_source() -> None:
    html = "<h2>Head</h2><p>One <b>bold</b> word.</p><math alttext='a+b'><mi>a</mi></math><ul><li>x</li><li>y</li></ul>"
    text = plain_text(html)
    assert "Head\n\nOne bold word." in text
    assert "a+b" in text and "x\n\ny" in text


def test_markdown_to_html_escapes_and_converts() -> None:
    html = markdown_to_html("## T <b>\n\npara [link](https://a.example/x)\n")
    assert "<h2>T &lt;b&gt;</h2>" in html and '<a href="https://a.example/x">link</a>' in html


def test_plain_abstract_strips_markup_and_prefix() -> None:
    assert plain_abstract("arXiv:2401.1 Announce Type: new Abstract: <p>Hello <b>world</b></p>") == "Hello world"
    assert plain_abstract(None) == "" and plain_abstract("") == ""


# --- default fetcher ---------------------------------------------------------------------------


def test_default_fetcher_routes_plain_requests_through_the_ladder(monkeypatch) -> None:
    from spyglass_service.fetch_types import AcquireResult

    seen = {}

    def fake_acquire(url, *, client, target_kind, rungs, start_tier):
        seen.update(url=url, kind=target_kind, start=start_tier)
        return AcquireResult(payload=b"<p>hi</p>", kind="bytes", final_url=url, content_type="text/html",
                             tier="T0", http_status=200, error=None, ok=True, encoding="utf-8")

    monkeypatch.setattr(http_mod, "acquire", fake_acquire)
    monkeypatch.setattr(http_mod, "build_rungs", lambda settings, kind, **kw: ())
    # The redirect pre-flight has its own tests; here it must not reach the network.
    monkeypatch.setattr(http_mod, "resolve_redirects", lambda client, url: RedirectOutcome(url))
    page = http_mod.make_fetcher(Settings())("https://example.com/a")
    assert page.ok and page.text == "<p>hi</p>" and seen["kind"] == "html"


def test_default_fetcher_reports_ladder_failures(monkeypatch) -> None:
    from spyglass_service.fetch_types import AcquireResult

    def fake_acquire(url, **kwargs):
        return AcquireResult(payload=b"", kind="bytes", final_url=url, content_type="", tier="T0",
                             http_status=403, error="HTTP 403", ok=False,
                             attempts=(("T0", 403, "HTTP 403"),))

    monkeypatch.setattr(http_mod, "acquire", fake_acquire)
    monkeypatch.setattr(http_mod, "build_rungs", lambda settings, kind, **kw: ())
    # The redirect pre-flight has its own tests; here it must not reach the network.
    monkeypatch.setattr(http_mod, "resolve_redirects", lambda client, url: RedirectOutcome(url))
    page = http_mod.make_fetcher(Settings())("https://example.com/a")
    assert not page.ok and page.status == 403 and page.error


def _imported_item(engine, url: str, via: str = "browser") -> int:
    """An item the reader imported themselves: a 700-word stored copy and the channel recorded."""
    item_id = _item(engine, url)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="article", html="<p>my copy</p>", status="ok",
                              word_count=700, title="My copy"))
        session.add(ItemState(item_id=item_id, from_user=True, captured_via=via))
        session.commit()
    return item_id


def _stored(engine, item_id: int) -> ReaderDoc:
    with Session(engine) as session:
        return session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()


def test_forced_refresh_keeps_an_imported_copy_when_the_rebuild_failed(engine) -> None:
    url = "https://news.example.org/mine"
    item_id = _imported_item(engine, url)
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True, fetch=FakeFetch({}))
    assert doc["status"] == "ok" and doc["html"] == "<p>my copy</p>"
    assert _stored(engine, item_id).html == "<p>my copy</p>"


def test_forced_refresh_keeps_an_imported_copy_when_the_rebuild_is_shorter(engine) -> None:
    url = "https://news.example.org/mine"
    item_id = _imported_item(engine, url, via="paste")
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True,
                            fetch=FakeFetch({url: _html_page(url, ARTICLE)}))
    assert doc["html"] == "<p>my copy</p>" and doc["word_count"] == 700
    assert _stored(engine, item_id).word_count == 700


def test_forced_refresh_keeps_an_imported_copy_when_the_network_is_down(engine) -> None:
    url = "https://news.example.org/mine"
    item_id = _imported_item(engine, url, via="file")
    down = Page(url=url, ok=False, error="The site could not be reached.", transient=True)
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True, fetch=FakeFetch({url: down}))
    assert doc["status"] == "ok" and doc["html"] == "<p>my copy</p>"


def test_forced_refresh_replaces_an_imported_copy_with_a_longer_good_rebuild(engine) -> None:
    url = "https://news.example.org/mine"
    item_id = _imported_item(engine, url)
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True,
                            fetch=FakeFetch({url: _html_page(url, BIG_ARTICLE)}))
    assert doc["status"] == "ok" and doc["word_count"] > 700
    assert _stored(engine, item_id).word_count > 700


def test_forced_refresh_still_replaces_a_copy_the_reader_did_not_import(engine) -> None:
    url = "https://news.example.org/theirs"
    item_id = _imported_item(engine, url, via="slack")
    doc = ensure_reader_doc(engine, Settings(), item_id, force=True,
                            fetch=FakeFetch({url: _html_page(url, ARTICLE)}))
    assert doc["word_count"] < 700 and "<h2>Method</h2>" in doc["html"]
