"""Tests for article extraction: boilerplate removal, structure kept, metadata and quality pick."""

from spyglass_service.radar.reader import article as article_mod
from spyglass_service.radar.reader import inline as inline_mod
from spyglass_service.radar.reader.article import (
    count_words, drop_duplicate_title, extract_article,
)

URL = "https://news.example.org/2026/story"
_PARAGRAPH = (
    "The research team described a new approach to reading medical images that cuts the time "
    "needed for a first review, and they tested it on several hospital datasets in three countries. "
)


def _page(body_extra: str = "", head_extra: str = "") -> str:
    """A small news page: navigation, ads and cookie banner around a real article."""
    return f"""<!doctype html><html><head><title>Big Story | Example News</title>
    <meta property="og:title" content="Big Story">
    <meta property="og:site_name" content="Example News">
    <meta property="og:image" content="/img/lead.jpg">
    <meta name="author" content="Ada Writer">{head_extra}
    <script>window.track=1</script></head><body>
    <nav><a href="/">Home</a> <a href="/world">World</a> <a href="/tech">Tech</a></nav>
    <div class="ad">BUY NOW limited offer click here</div>
    <article><h1>Big Story</h1><p class="byline">By Ada Writer</p>
    <p>{_PARAGRAPH * 3}</p>
    <h2>The method</h2>
    <p>{_PARAGRAPH * 3}</p>
    <figure><img data-src="/img/chart.png" src="data:image/gif;base64,R0lGOD" alt="A chart" width="600">
    <figcaption>Figure 1: results</figcaption></figure>
    <table><tr><th>Model</th><th>Score</th></tr><tr><td>A</td><td>0.91</td></tr></table>
    <p>{_PARAGRAPH * 3}</p>{body_extra}</article>
    <footer>Copyright Example News. Subscribe to our newsletter.</footer></body></html>"""


def test_extracts_article_with_structure_images_and_tables() -> None:
    result = extract_article(_page(), URL)
    html = result["html"]
    assert "<h2>The method</h2>" in html
    assert "<table" in html and "0.91" in html
    assert 'src="https://news.example.org/img/chart.png"' in html
    assert "BUY NOW" not in html
    assert "Subscribe to our newsletter" not in html
    assert "<script" not in html
    assert result["word_count"] > 100


def test_metadata_comes_from_page_tags() -> None:
    result = extract_article(_page(), URL)
    assert result["title"] == "Big Story"
    assert result["byline"] == "Ada Writer"
    assert result["site"] == "Example News"
    assert result["lead_image"] == "https://news.example.org/img/lead.jpg"


def test_leading_heading_that_repeats_the_title_is_removed() -> None:
    result = extract_article(_page(), URL)
    assert "<h1>Big Story</h1>" not in result["html"]


def test_site_suffix_is_stripped_from_title() -> None:
    page = _page().replace('<meta property="og:title" content="Big Story">',
                           '<meta property="og:title" content="Big Story | Example News">')
    assert extract_article(page, URL)["title"] == "Big Story"


def test_empty_or_unreadable_page_returns_no_text() -> None:
    assert extract_article("", URL)["word_count"] == 0
    assert extract_article("<html><body><nav><a href='/'>x</a></nav></body></html>", URL)["word_count"] < 5


def test_script_in_article_body_is_removed() -> None:
    page = _page(body_extra='<p>tail</p><script>alert(1)</script><img src=x onerror="alert(1)">')
    html = extract_article(page, URL)["html"]
    assert "alert(1)" not in html and "onerror" not in html


def test_drop_duplicate_title_keeps_other_headings() -> None:
    html = "<h1>My Title</h1><h2>Other</h2><p>text</p>"
    out = drop_duplicate_title(html, "My Title")
    assert "My Title" not in out and "<h2>Other</h2>" in out
    assert "<h1>My Title</h1>" in drop_duplicate_title(html, "Unrelated")


def test_count_words_ignores_markup() -> None:
    assert count_words("<p>one <b>two</b></p><p>three</p>") == 3


def test_pick_prefers_the_richer_extraction_but_not_link_lists() -> None:
    long_text = "<p>" + "word " * 200 + "</p>"
    links = "<p>" + "".join(f'<a href="/{i}">link number {i}</a> ' for i in range(120)) + "</p>"
    assert article_mod._pick(long_text, links) == long_text
    assert article_mod._pick(links, long_text) == long_text


def test_pick_prefers_trafilatura_when_it_keeps_most_of_the_text() -> None:
    traf = "<p>" + "word " * 180 + "</p>"
    read = "<p>" + "word " * 200 + "</p>"
    assert article_mod._pick(traf, read) == traf


def test_pick_counts_images_as_content() -> None:
    plain = "<p>" + "word " * 100 + "</p>"
    illustrated = "<p>" + "word " * 60 + "</p>" + '<img src="/a.png">' * 6
    assert article_mod._pick(plain, illustrated) == illustrated


def test_pick_with_nothing_returns_empty() -> None:
    assert article_mod._pick("", "  ") == ""


def test_spaces_next_to_inline_elements_survive_extraction() -> None:
    """Sites that put a trailing space inside a <span> must not lose it before a link or emphasis."""
    spaced = (
        "<blockquote><p><strong>A Free Bonus Chapter!</strong><span> </span><br/><br/>"
        "<span>This was a chapter of our recently released book, </span>"
        "<em><a href='https://x.example/a'>An Illustrated Guide</a><span> </span></em>"
        "<span>but we created just too many visuals.</span><br/><br/>"
        "<span>But it should not go to waste. As with our </span>"
        "<a href='https://x.example/b'>previous book</a>"
        "<span>, we love creating free </span><strong>bonus content</strong><span> for people who "
        "supported us over the years.</span></p></blockquote>"
    )
    result = extract_article(_page(body_extra=spaced), URL)
    text = " ".join(result["html"].split())
    assert "with our <a" in text and "</a>, we love" in text
    assert "free <strong>bonus content</strong> for people" in text or \
        "free <b>bonus content</b> for people" in text or "free <i>bonus content</i> for people" in text


def test_inline_spaces_survive_in_list_items_and_bare_text() -> None:
    """Trafilatura also trims around inline elements in list items and bare text in a div."""
    body = ("<ul><li>As with our <a href='https://x.example/b'>previous book</a>, we love "
            "<b>bonus</b> content for people who read.</li><li>Second item here.</li></ul>")
    text = " ".join(extract_article(_page(body_extra=body), URL)["html"].split())
    assert "with our <a" in text and "love <strong>bonus</strong> content" in text


def test_protect_inline_spaces_marks_only_spaces_next_to_words() -> None:
    """Whitespace between block elements is left alone; the mark never survives extraction."""
    marked = inline_mod.protect_inline("<p>say <a>this</a> now</p>\n<a>x</a>")
    assert marked.count(inline_mod._SPACE_MARK) == 2
    assert inline_mod._SPACE_MARK not in extract_article(_page(), URL)["html"]
