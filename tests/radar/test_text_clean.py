"""Tests for text_clean: one-line cleaning (clean_line) and the multi-line rule for notes (clean_text)."""

from spyglass_service.radar.text_clean import ELLIPSIS, clean_line, clean_text


def test_clean_text_keeps_line_breaks_of_every_kind_as_newlines() -> None:
    assert clean_text("a\r\nb\rc\nd", 50) == "a\nb\nc\nd"


def test_clean_text_turns_other_control_characters_into_spaces_and_collapses_them() -> None:
    assert clean_text("one\ttwo\x07  three\nfour   five", 50) == "one two three\nfour five"


def test_clean_text_removes_invisible_formatting_characters() -> None:
    # A zero-width space and a right-to-left override, as text pasted from a message may carry.
    assert clean_text("pay​load‮ here", 50) == "payload here"


def test_clean_text_keeps_one_blank_line_between_paragraphs_at_most() -> None:
    assert clean_text("first\n\n\n\n second \n\nthird", 50) == "first\n\nsecond\n\nthird"


def test_clean_text_drops_blank_lines_at_the_start_and_end() -> None:
    assert clean_text("\n \n  text  \n\n", 50) == "text"


def test_clean_text_treats_unicode_line_separators_as_line_breaks() -> None:
    assert clean_text("a b c", 50) == "a\nb\nc"


def test_clean_text_cuts_to_the_limit_with_an_ellipsis() -> None:
    text = clean_text("x" * 2100, 2000)
    assert len(text) == 2000
    assert text.endswith(ELLIPSIS)


def test_clean_text_of_nothing_is_empty() -> None:
    assert clean_text(None, 10) == ""
    assert clean_text("  \n\t ", 10) == ""


def test_clean_line_still_makes_one_line() -> None:
    assert clean_line("a\nb\tc", 50) == "a b c"
