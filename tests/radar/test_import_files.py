"""Tests for the conversions behind "Paste the text" and "Add a file"."""

import pytest

from spyglass_service.radar import import_files
from spyglass_service.radar.import_files import ImportRefused

MHTML = (
    b"From: <Saved by Blink>\r\n"
    b"Snapshot-Content-Location: https://news.example.com/story\r\n"
    b"Subject: A story\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/related; type="text/html"; boundary="----B"\r\n'
    b"\r\n"
    b"------B\r\n"
    b"Content-Type: text/html\r\n"
    b"Content-ID: <frame-1" b"@mhtml.blink>\r\n"
    b"Content-Transfer-Encoding: quoted-printable\r\n"
    b"Content-Location: https://news.example.com/story\r\n"
    b"\r\n"
    b"<html><head><meta charset=3D\"utf-8\"><title>A story</title></head><body><p>Caf=C3=A9 =\r\n"
    b"opens.</p></body></html>\r\n"
    b"------B\r\n"
    b"Content-Type: image/png\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b"Content-Location: https://news.example.com/a.png\r\n"
    b"\r\n"
    b"iVBORw0KGgo=\r\n"
    b"------B--\r\n"
)


def test_plain_text_becomes_escaped_paragraphs() -> None:
    html = import_files.text_to_html("First <b>line</b>\nsame paragraph\r\n\r\n\nSecond & last")
    assert html == "<p>First &lt;b&gt;line&lt;/b&gt;<br>same paragraph</p><p>Second &amp; last</p>"


def test_empty_text_gives_no_paragraphs() -> None:
    assert import_files.text_to_html("  \n\n ") == ""


@pytest.mark.parametrize("text,expected", [
    ("<article><p>Hi</p><p>there</p></article>", True),
    ("<!DOCTYPE html><html><body>x</body></html>", True),
    ("I think 3 < 4 and <b> is bold", False),
    ("Plain words only.\n\nMore words.", False),
])
def test_html_source_is_told_apart_from_prose(text: str, expected: bool) -> None:
    assert import_files.looks_like_html(text) is expected


def test_the_first_short_line_is_a_title() -> None:
    assert import_files.first_line_title("Big news today\n\nThe body follows.") == "Big news today"
    assert import_files.first_line_title("Only one line") == ""
    assert import_files.first_line_title("x" * 300 + "\nbody") == ""


def test_a_saved_page_is_decoded_with_its_declared_charset() -> None:
    data = '<html><head><meta charset="windows-1252"></head><body><p>Café</p></body></html>'.encode("cp1252")
    assert "Café" in import_files.decode_html_bytes(data)


def test_a_utf8_page_is_decoded() -> None:
    assert "naïve" in import_files.decode_html_bytes("<p>naïve</p>".encode())


def test_the_web_page_is_taken_from_an_mhtml_archive() -> None:
    page = import_files.page_from_file("story.mhtml", MHTML)
    assert "<title>A story</title>" in page
    assert "Café opens." in page


def test_an_archive_without_a_page_is_refused() -> None:
    data = b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
    with pytest.raises(ImportRefused):
        import_files.mhtml_html(data)


@pytest.mark.parametrize("name,data,kind", [
    ("paper.pdf", b"%PDF-1.7\n...", "pdf"),
    ("Paper.PDF", b"\xef\xbb\xbf%PDF-1.4", "pdf"),
    ("page.html", b"<p>x</p>", "html"),
    ("page.htm", b"<p>x</p>", "html"),
    ("page.mhtml", MHTML, "mhtml"),
    ("page.mht", MHTML, "mhtml"),
])
def test_the_file_kind_comes_from_the_name_and_a_pdf_must_be_one(name: str, data: bytes, kind: str) -> None:
    assert import_files.file_kind(name, data) == kind


@pytest.mark.parametrize("name,data", [
    ("fake.pdf", b"<html>not a pdf</html>"),
    ("notes.docx", b"PK\x03\x04"),
    ("noext", b"<p>x</p>"),
    ("empty.html", b""),
])
def test_other_files_are_refused(name: str, data: bytes) -> None:
    with pytest.raises(ImportRefused):
        import_files.file_kind(name, data)


def test_the_file_limit_is_150_megabytes_and_the_byte_limit_follows_it() -> None:
    assert import_files.MAX_FILE_MB == 150
    assert import_files.MAX_FILE_BYTES == 150 * 1024 * 1024


def test_a_file_over_the_limit_is_refused_with_the_limit_in_the_message(monkeypatch) -> None:
    monkeypatch.setattr(import_files, "MAX_FILE_BYTES", 10)
    with pytest.raises(ImportRefused, match="150 MB"):
        import_files.file_kind("a.html", b"<p>" + b"x" * 20 + b"</p>")


def test_a_page_over_the_page_limit_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(import_files, "MAX_PAGE_BYTES", 10)
    with pytest.raises(ImportRefused):
        import_files.page_from_file("a.html", b"<p>" + b"x" * 20 + b"</p>")


def test_a_pdf_is_not_a_web_page() -> None:
    with pytest.raises(ImportRefused):
        import_files.page_from_file("a.pdf", b"%PDF-1.4 rest")


def test_pdf_text_uses_the_shared_extractor(monkeypatch) -> None:
    monkeypatch.setattr(import_files, "extract_pdf", lambda data: "  Text of the paper \n")
    assert import_files.pdf_text(b"%PDF-1.4") == "Text of the paper"


def test_a_damaged_pdf_gives_no_text() -> None:
    assert import_files.pdf_text(b"%PDF-1.4 this is not really a pdf") == ""
