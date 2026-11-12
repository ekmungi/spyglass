"""Regression tests for inline code and for whitespace at inline boundaries in extracted articles."""

import re

from bs4 import BeautifulSoup

from spyglass_service.radar.reader.article import extract_article

_FILLER = ("<p>" + "The filler sentence talks about the topic with enough words to make the page "
           "look like a real article for the extractors. " * 6 + "</p>")


def _extract(body: str) -> str:
    """The extracted HTML of an article page whose body holds `body` between two filler paragraphs."""
    page = (f"<html><head><title>T</title></head><body><article><h1>Heading of the page</h1>"
            f"{_FILLER}{body}{_FILLER}</article></body></html>")
    return extract_article(page, "https://x.example/post")["html"]


def _text_of(html: str, marker: str) -> str:
    """The visible text of the block that contains `marker`, whitespace collapsed."""
    soup = BeautifulSoup(html, "html.parser")
    block = next(t for t in soup.find_all(["p", "li", "h4", "td", "blockquote"]) if marker in t.get_text())
    return re.sub(r"\s+", " ", block.get_text(""))


# --- inline code -------------------------------------------------------------------------------


def test_inline_code_stays_inside_its_paragraph() -> None:
    html = _extract("<p>It is a local proxy, <code>bili</code>, that sits between a coding agent and its model API.</p>")
    soup = BeautifulSoup(html, "html.parser")
    paragraph = next(p for p in soup.find_all("p") if "local proxy" in p.get_text())
    assert paragraph.find("code").get_text() == "bili"
    assert "that sits between a coding agent" in paragraph.get_text()
    assert not soup.find("pre")


def test_inline_code_in_list_items_and_text_around_it_is_kept() -> None:
    html = _extract("<ul><li>The <code>compress</code>: fold a range of messages into a summary.</li>"
                    "<li>The <code>decompress</code>: restore a folded range of messages.</li></ul>")
    soup = BeautifulSoup(html, "html.parser")
    items = [li for li in soup.find_all("li") if "folded" in li.get_text() or "summary" in li.get_text()]
    assert len(items) == 2 and all(li.find("code") and not li.find("pre") for li in items)
    assert "The compress: fold" in _text_of(html, "summary")


def test_several_inline_code_spans_in_one_sentence() -> None:
    html = _extract("<p>Use <code>npm install</code> to install and then run <code>bili --version</code> to check the build.</p>")
    soup = BeautifulSoup(html, "html.parser")
    paragraph = next(p for p in soup.find_all("p") if "to install" in p.get_text())
    assert [c.get_text() for c in paragraph.find_all("code")] == ["npm install", "bili --version"]
    assert not soup.find("pre")
    assert _text_of(html, "to install") == "Use npm install to install and then run bili --version to check the build."


def test_inline_code_is_escaped() -> None:
    html = _extract("<p>Write <code>a &lt; b &amp;&amp; c</code> in the condition of the loop to compare.</p>")
    assert "<code>a &lt; b &amp;&amp; c</code>" in html


def test_block_code_stays_a_pre_with_code_inside() -> None:
    html = _extract("<pre><code>npm install -g tool\ntool --version</code></pre>")
    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre")
    assert pre is not None and pre.find("code") is not None
    assert "npm install -g tool\ntool --version" in pre.get_text()


def test_plain_pre_block_gets_a_code_child() -> None:
    soup = BeautifulSoup(_extract("<pre>line one\nline two</pre>"), "html.parser")
    assert soup.find("pre").find("code") is not None


# --- whitespace at inline boundaries -----------------------------------------------------------


def test_space_before_a_link_inside_nested_spans_is_kept() -> None:
    html = _extract('<ul><li><span><span>sought to raise money, and the firm <a href="https://x.example/a">'
                    "<span><span>plans to buy</span></span></a><span><span> artificial intelligence "
                    "company Counsel for cash.</span></span></span></span></li></ul>")
    assert "plans to buy artificial intelligence" in _text_of(html, "plans to buy")


def test_space_inside_a_link_that_holds_only_a_space_is_kept() -> None:
    html = _extract('<p>All of this work is public in the <a href="https://x.example/a"> </a>'
                    '<a href="https://x.example/b">Agent Substrate repository</a>: read it today and tell us.</p>')
    assert "in the Agent Substrate repository" in _text_of(html, "Agent Substrate")


def test_space_before_link_after_text_in_a_span_and_after_the_link() -> None:
    html = _extract('<p>He wrote <span>since </span><a href="https://x.example/a">crossing $100M ARR</a>'
                    ' in the quarter, and <b>bold</b> <a href="https://x.example/b">second</a> end of the sentence.</p>')
    text = _text_of(html, "crossing")
    assert "since crossing $100M ARR in the quarter" in text and "bold second end" in text


def test_space_between_a_link_and_following_inline_markup_in_headings_and_cells() -> None:
    html = _extract('<h4>Recent in <a href="https://x.example/a">Sectors</a></h4>'
                    '<table><tr><td>Model <a href="https://x.example/a">one</a> base</td><td>CC BY 4.0</td></tr></table>')
    assert "Recent in Sectors" in _text_of(html, "Sectors")
    assert "Model one base" in _text_of(html, "Model")


def test_blockquote_text_keeps_its_spaces_around_links_and_code() -> None:
    html = _extract('<blockquote><p>Read <a href="https://x.example/a">the note</a> and run <code>make</code> before you '
                    "start work on the next part of the long task list.</p></blockquote>")
    assert "Read the note and run make before" in _text_of(html, "the note")


# --- tables ------------------------------------------------------------------------------------


def test_table_rows_and_cells_survive_extraction() -> None:
    rows = "".join(f"<tr><td>Name {i}</td><td>{i}.5%</td></tr>" for i in range(6))
    html = _extract(f"<table><tr><th>Transcriber</th><th>Error</th></tr>{rows}</table>")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    assert table is not None and len(table.find_all("tr")) >= 7
    assert [c.get_text() for c in table.find_all("tr")[1].find_all("td")] == ["Name 0", "0.5%"]
    assert not soup.find("row") and not soup.find("cell")


def test_space_between_two_touching_inline_elements_is_added() -> None:
    html = _extract('<p>Sponsored content for you today, <span>Provided by</span><a href="https://x.example/a">HPE</a>'
                    " and further words so that the paragraph is long enough to be kept by the extractor.</p>")
    assert "Provided by HPE" in _text_of(html, "Provided by")
