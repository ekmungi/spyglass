"""Tests for the YouTube builder: id parsing, transcript paragraphs and the no-transcript case."""

import pytest

from spyglass_service.radar.reader.video import (
    build_video, embed_url, paragraphs_from_transcript, youtube_id,
)


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=N5YLi8Ar3Wg", "N5YLi8Ar3Wg"),
    ("https://www.youtube.com/watch?feature=share&v=N5YLi8Ar3Wg&t=10", "N5YLi8Ar3Wg"),
    ("https://youtu.be/N5YLi8Ar3Wg?si=abc", "N5YLi8Ar3Wg"),
    ("https://www.youtube.com/shorts/N5YLi8Ar3Wg", "N5YLi8Ar3Wg"),
    ("https://www.youtube-nocookie.com/embed/N5YLi8Ar3Wg", "N5YLi8Ar3Wg"),
])
def test_youtube_id_forms(url: str, expected: str) -> None:
    assert youtube_id(url) == expected


@pytest.mark.parametrize("url", ["https://example.com/watch?v=abcdefghijk", "https://www.youtube.com/", ""])
def test_youtube_id_rejects_other_urls(url: str) -> None:
    assert youtube_id(url) is None


def test_embed_url_is_cookie_free() -> None:
    assert embed_url("abc123DEF45") == "https://www.youtube-nocookie.com/embed/abc123DEF45"


def test_sentences_are_grouped_into_paragraphs() -> None:
    text = " ".join(f"This is sentence number {i} of the talk." for i in range(10))
    paragraphs = paragraphs_from_transcript(text)
    assert len(paragraphs) == 3  # 4 + 4 + 2 sentences
    assert all(p.startswith("<p>") and p.endswith("</p>") for p in paragraphs)


def test_unpunctuated_captions_are_cut_by_word_count() -> None:
    text = " ".join(f"word{i}" for i in range(300))
    assert len(paragraphs_from_transcript(text)) > 1


def test_timestamped_lines_keep_a_time_element() -> None:
    paragraphs = paragraphs_from_transcript("0:05 Hello there\n1:20 Second part")
    assert paragraphs[0] == "<p><time>0:05</time> Hello there</p>"
    assert len(paragraphs) == 2


def test_transcript_text_is_escaped() -> None:
    html = "".join(paragraphs_from_transcript("Use <script>alert(1)</script> carefully."))
    assert "<script>" not in html


def test_empty_transcript_gives_no_paragraphs() -> None:
    assert paragraphs_from_transcript("") == []


def test_build_video_uses_the_transcriber_and_embed() -> None:
    result = build_video("N5YLi8Ar3Wg", url="https://youtu.be/N5YLi8Ar3Wg", title="A talk", origin="A channel",
                         stored_text=None, transcriber=lambda vid: "First point. Second point. Third point.")
    assert result["kind"] == "video"
    assert result["alt_url"] == "https://www.youtube-nocookie.com/embed/N5YLi8Ar3Wg"
    assert "First point." in result["html"]
    assert result["site"] == "YouTube" and result["byline"] == "A channel"
    assert result["lead_image"].endswith("/N5YLi8Ar3Wg/hqdefault.jpg")
    assert result["word_count"] == 6


def test_stored_transcript_is_preferred_to_fetching() -> None:
    def explode(video_id: str) -> str:
        raise AssertionError("must not fetch when text is stored")

    result = build_video("N5YLi8Ar3Wg", url="u", title="t", origin="", stored_text="Already here.",
                         transcriber=explode)
    assert "Already here." in result["html"]


def test_missing_transcript_still_gives_an_ok_document_with_notice() -> None:
    result = build_video("N5YLi8Ar3Wg", url="https://youtu.be/N5YLi8Ar3Wg", title="t", origin="",
                         stored_text="", transcriber=lambda vid: None)
    assert "No transcript is available" in result["html"]
    assert result["alt_url"].endswith("N5YLi8Ar3Wg")
    assert result["word_count"] == 0


def test_transcriber_errors_are_contained() -> None:
    def broken(video_id: str) -> str:
        raise RuntimeError("blocked")

    result = build_video("N5YLi8Ar3Wg", url="u", title="t", origin="", stored_text=None, transcriber=broken)
    assert "No transcript is available" in result["html"]
