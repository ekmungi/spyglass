"""Regression tests for reader content quality: service markdown, stub pages, previews, noise."""

import pytest
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.models import ReaderDoc
from spyglass_service.radar.reader.blocked import STUB_REASON, is_stub_page, looks_blocked, registrable_domain
from spyglass_service.radar.reader.build import ensure_reader_doc
from spyglass_service.radar.reader.http import Page
from spyglass_service.radar.reader.noise import strip_page_noise
from spyglass_service.radar.reader.paywall import PARTIAL_NOTICE, looks_partial
from spyglass_service.radar.serialize import radar_items

_SENTENCE = ("The hospital group measured how often the system flagged real findings in the scans "
             "it reviewed during the study period across several sites, and then compared those results with "
             "the reports that the radiologists had written. ")
LONG = _SENTENCE * 4  # about 100 words in one paragraph


# --- registrable domain ------------------------------------------------------------------------


@pytest.mark.parametrize("url, expected", [
    ("https://www.fiercehealthcare.com/a/b", "fiercehealthcare.com"),
    ("https://news.bbc.co.uk/x", "bbc.co.uk"),
    ("https://hb.trustedstack.com/cksync?x=1", "trustedstack.com"),
    ("not a url", ""),
])
def test_registrable_domain(url: str, expected: str) -> None:
    assert registrable_domain(url) == expected


# --- stub pages --------------------------------------------------------------------------------


def test_other_domain_with_few_words_is_a_stub() -> None:
    assert is_stub_page("A short note about nothing in particular.", "https://a.example/story",
                        "https://tracker.example.net/sync")


def test_other_domain_with_a_real_article_passes() -> None:
    assert not is_stub_page(LONG * 2, "https://a.example/story", "https://b.example.org/story")


def test_same_registrable_domain_redirect_with_a_real_paragraph_passes() -> None:
    text = "Short post.\n\n" + _SENTENCE
    assert not is_stub_page(text, "https://example.com/p", "https://blog.example.com/p")


def test_pixel_description_is_a_stub() -> None:
    assert is_stub_page("A 1x1 image, likely a tracker probe", "https://a.example/x", "https://a.example/x")


def test_short_text_without_a_substantial_paragraph_is_a_stub() -> None:
    text = "Share this story.\n\nRelated stories\n\nSign up for our newsletter today.\n\n" + "word " * 20
    assert is_stub_page(text, "https://a.example/x", "https://a.example/x")


def test_short_post_with_one_real_paragraph_passes() -> None:
    assert not is_stub_page(_SENTENCE, "https://a.example/x", "https://a.example/x")
    assert not is_stub_page("Heading\n\n" + _SENTENCE, "https://a.example/x", "https://a.example/x")


def test_long_text_is_never_a_stub_for_missing_paragraph_shape() -> None:
    assert not is_stub_page("one two three. " * 40, "https://a.example/x", "https://a.example/x")


def test_security_verification_wall_is_a_block_page() -> None:
    text = ("Performing security verification This website uses a security service to protect against "
            "malicious bots. This page is displayed while the website verifies you are not a bot.")
    assert looks_blocked(text, "Just a moment...")
    assert looks_blocked(text, "")


def test_firewall_notice_page_is_a_block_page() -> None:
    text = ("This website is using a security service to protect itself from online attacks. The action you "
            "just performed triggered the security solution. There are several actions that could trigger "
            "this block including submitting a certain word or phrase, a SQL command or malformed data.")
    assert looks_blocked(text, "")


# --- previews ----------------------------------------------------------------------------------


def test_paywalled_host_with_short_text_is_partial() -> None:
    assert looks_partial(_SENTENCE * 3, "https://www.wsj.com/tech/story", "https://www.wsj.com/tech/story")


def test_paywalled_host_with_a_long_text_is_not_partial() -> None:
    assert not looks_partial(_SENTENCE * 40, "https://www.nytimes.com/x", "https://www.nytimes.com/x")


def test_host_match_is_by_domain_not_substring() -> None:
    assert not looks_partial(_SENTENCE * 2, "https://soft.com/x", "https://soft.com/x")
    assert not looks_partial(_SENTENCE * 2, "https://notft.com.example.org/x", "https://notft.com.example.org/x")


def test_subscribe_phrase_on_a_short_text_is_partial_anywhere() -> None:
    text = _SENTENCE * 2 + "Subscribe to continue reading this article."
    assert looks_partial(text, "https://local.example/x", "https://local.example/x")


def test_subscribe_phrase_in_a_long_article_is_not_partial() -> None:
    text = _SENTENCE * 40 + "Already a subscriber? Sign in."
    assert not looks_partial(text, "https://local.example/x", "https://local.example/x")


def test_statnews_is_partial_only_for_its_plus_articles() -> None:
    assert looks_partial("STAT+ Exclusive " + _SENTENCE * 3, "https://www.statnews.com/2026/11/10/x/",
                         "https://www.statnews.com/2026/11/10/x/")
    assert not looks_partial(_SENTENCE * 3, "https://www.statnews.com/2026/11/10/x/",
                             "https://www.statnews.com/2026/11/10/x/")


# --- noise -------------------------------------------------------------------------------------


def test_ticker_fragment_is_removed_and_its_empty_block_pruned() -> None:
    html = ("<p>Chips rose.</p><p>NVDA 2.87%increase; up pointing triangle</p>"
            "<p>Nvidia NVDA 2.87%increase; up pointing triangle gained on Monday.</p>")
    out = strip_page_noise(html)
    assert "triangle" not in out and "2.87" not in out
    assert out.count("<p>") == 2 and "Nvidia" in out and "gained on Monday" in out


def test_bare_hash_tokens_are_removed_but_normal_words_stay() -> None:
    html = ("<p>9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08</p>"
            "<p>Keep this sentence, which mentions Pneumonoultramicroscopicsilicovolcanoconiosis.</p>"
            "<pre>9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08</pre>")
    out = strip_page_noise(html)
    assert out.count("9f86d081") == 1  # only the one in the code block remains
    assert "Keep this sentence" in out and "Pneumonoultra" in out


# --- build level -------------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path):
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def _item(engine, url: str, title: str = "An item") -> int:
    with Session(engine) as session:
        item = Item(source="rss", external_id=url, title=title, url=url, origin="Pub")
        session.add(item)
        session.commit()
        return item.id


def _fetch(page: Page):
    return lambda url, headers=None: page


def _markdown_page(url: str, text: str) -> Page:
    return Page(url=url, ok=True, body=text.encode(), content_type="text/plain", status=200, is_markdown=True)


def _html_page(url: str, html: str) -> Page:
    return Page(url=url, ok=True, body=html.encode(), content_type="text/html", status=200)


def test_service_markdown_becomes_a_clean_article_without_the_header(engine) -> None:
    url = "https://news.example.org/deal"
    item_id = _item(engine, url, "Feed title")
    text = ("Title: Deerfield taps AWS\n\nURL Source: " + url + "\n\nPublished Time: 2026-11-09T09:00:00-0500\n\n"
            "Warning: This is a cached snapshot of the original page, consider retry with caching opt-out.\n\n"
            "Markdown Content:\n## Why\n\n" + LONG.replace("hospital", "**hospital**") + "\n\n- first point\n- second point\n")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=_fetch(_markdown_page(url, text)))
    assert doc["status"] == "ok" and doc["title"] == "Deerfield taps AWS"
    html = doc["html"]
    assert "Markdown Content" not in html and "URL Source" not in html and "Warning" not in html
    assert "<strong>hospital</strong>" in html and "<h2>Why</h2>" in html and "<li>first point</li>" in html
    assert "**" not in html
    assert "2026" in (doc["byline"] or "")
    assert doc["partial"] is False and doc["notice"] is None


def test_tracker_stub_stored_as_failed_with_the_standard_reason(engine) -> None:
    url = "https://www.fiercehealthcare.com/ai/story"
    item_id = _item(engine, url)
    text = ("Title: https://hb.trustedstack.com/cksync\n\nURL Source: " + url + "\n\n"
            "Final URL: https://hb.trustedstack.com/cksync?cs=91\n\n"
            "Warning: This is a cached snapshot of the original page.\n\n"
            "Markdown Content: A 1x1 image, likely be a tacker probe")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=_fetch(_markdown_page("https://hb.trustedstack.com/cksync", text)))
    assert doc["status"] == "failed" and doc["error"] == STUB_REASON == "No readable article was found at this address."
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first().status == "failed"


def test_html_page_that_redirected_to_another_site_with_little_text_fails(engine) -> None:
    item_id = _item(engine, "https://a.example/story")
    page = _html_page("https://sync.other.net/x", f"<html><body><article><p>{_SENTENCE}</p></article></body></html>")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=_fetch(page))
    assert doc["status"] == "failed" and doc["error"] == STUB_REASON


def test_short_legitimate_post_with_one_paragraph_is_still_an_article(engine) -> None:
    url = "https://blog.example.org/note"
    item_id = _item(engine, url)
    page = _html_page(url, f"<html><head><title>Note</title></head><body><article><h1>Note</h1><p>{_SENTENCE}</p></article></body></html>")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=_fetch(page))
    assert doc["status"] == "ok" and doc["partial"] is False


def test_paywalled_preview_is_kept_marked_partial_and_stays_readable(engine) -> None:
    url = "https://www.wsj.com/tech/ai-story"
    item_id = _item(engine, url)
    body = (f"<p>{_SENTENCE * 2}</p><p>NVDA 2.87%increase; up pointing triangle</p>"
            "<p>9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08</p>"
            "<p>Subscribe to continue reading.</p>")
    page = _html_page(url, f"<html><head><title>Story</title></head><body><article><h1>Story</h1>{body}</article></body></html>")
    doc = ensure_reader_doc(engine, Settings(), item_id, fetch=_fetch(page))
    assert doc["status"] == "ok" and doc["partial"] is True and doc["notice"] == PARTIAL_NOTICE
    assert "triangle" not in doc["html"] and "9f86d081" not in doc["html"]
    with Session(engine) as session:
        assert session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first().status == "partial"
        assert radar_items(session, [item_id])[0]["has_reader"] is True
    again = ensure_reader_doc(engine, Settings(), item_id, fetch=lambda *a, **k: pytest.fail("refetched"))
    assert again["partial"] is True and again["notice"] == PARTIAL_NOTICE
