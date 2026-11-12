"""Tests for the markdown converter and the fetch-service header parser used by the reader."""

from spyglass_service.radar.reader.markdown import markdown_to_html, parse_fetch_markdown

SERVICE_OUTPUT = (
    "Title: Deerfield taps AWS\n\n"
    "URL Source: https://news.example.org/deal\n\n"
    "Published Time: 2026-11-09T09:00:00-0500\n\n"
    "Warning: This is a cached snapshot of the original page, consider retry with caching opt-out.\n\n"
    "Markdown Content:\n"
    "Deerfield is **tapping** AWS.\n\nSecond paragraph.\n"
)


# --- header ------------------------------------------------------------------------------------


def test_header_fields_are_parsed_and_body_starts_after_the_marker() -> None:
    parsed = parse_fetch_markdown(SERVICE_OUTPUT)
    assert parsed.title == "Deerfield taps AWS"
    assert parsed.source_url == "https://news.example.org/deal"
    assert parsed.published == "2026-11-09T09:00:00-0500"
    assert parsed.body.startswith("Deerfield is **tapping** AWS.")
    assert "Title:" not in parsed.body and "URL Source" not in parsed.body


def test_cached_snapshot_notice_is_dropped_and_error_warnings_are_recorded() -> None:
    parsed = parse_fetch_markdown(SERVICE_OUTPUT)
    assert parsed.warnings == ()
    refused = parse_fetch_markdown(
        "Title: Page Unavailable\nURL Source: https://a.example/x\n"
        "Warning: Target URL returned error 403: Forbidden\n"
        "Warning: This page maybe requiring CAPTCHA, please make sure you are authorized to access this page.\n"
        "Markdown Content:\nPlease be advised that this page is unavailable.\n"
    )
    assert len(refused.warnings) == 2 and refused.target_error == 403


def test_body_on_the_marker_line_and_final_url_are_handled() -> None:
    parsed = parse_fetch_markdown(
        "Title: https://hb.example/sync\nURL Source: https://a.example/story\n"
        "Final URL: https://hb.example/sync?x=1\nMarkdown Content: A 1x1 image, probe\n"
    )
    assert parsed.body == "A 1x1 image, probe"
    assert parsed.final_url == "https://hb.example/sync?x=1"
    assert parsed.title == "https://hb.example/sync"


def test_plain_markdown_without_header_is_returned_untouched() -> None:
    parsed = parse_fetch_markdown("# Heading\n\nTitle: this is just a sentence in a paragraph.")
    assert parsed.title == "" and parsed.body.startswith("# Heading")


def test_header_without_a_marker_stops_at_the_first_other_line() -> None:
    parsed = parse_fetch_markdown("Title: T\nURL Source: https://a.example/\n\nBody text here.\n")
    assert parsed.title == "T" and parsed.body == "Body text here."


# --- inline ------------------------------------------------------------------------------------


def test_bold_italic_strike_and_links() -> None:
    html = markdown_to_html("A **bold** and *italic* and __b2__ and _i2_ and ~~gone~~ [site](https://a.example/p?x=1&y=2).")
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<strong>b2</strong>" in html and "<em>i2</em>" in html and "<del>gone</del>" in html
    assert '<a href="https://a.example/p?x=1&amp;y=2">site</a>' in html
    assert "**" not in html


def test_snake_case_and_math_stars_are_not_emphasis() -> None:
    html = markdown_to_html("Call my_function_name with 2 * 3 * 4 now.")
    assert "<em>" not in html and "my_function_name" in html


def test_inline_code_is_protected_from_emphasis_and_html() -> None:
    html = markdown_to_html("Run `a **b** <x>` then done.")
    assert "<code>a **b** &lt;x&gt;</code>" in html and "<strong>" not in html


def test_images_including_linked_images_and_service_alt_prefix() -> None:
    html = markdown_to_html("![Image 1: A chart](https://a.example/c.png)\n\n[![Logo](https://a.example/l.png)](https://a.example/)")
    assert '<img alt="A chart" src="https://a.example/c.png">' in html
    assert '<a href="https://a.example/"><img alt="Logo" src="https://a.example/l.png"></a>' in html


def test_space_is_restored_where_the_service_glued_a_link_to_a_word() -> None:
    html = markdown_to_html("Recommended rates of[just 29% to 39%](https://a.example/x) were found.")
    assert "rates of <a" in html
    assert "(https" not in html


def test_html_in_markdown_is_escaped() -> None:
    assert "&lt;script&gt;" in markdown_to_html("Hello <script>alert(1)</script>")


# --- blocks ------------------------------------------------------------------------------------


def test_headings_paragraphs_and_rules() -> None:
    html = markdown_to_html("# One\n\nline a\nline b\n\n### Three ###\n\n---\n\nend")
    assert html.startswith("<h1>One</h1><p>line a line b</p><h3>Three</h3><hr>")
    assert html.endswith("<p>end</p>")


def test_unordered_and_ordered_lists_with_nesting() -> None:
    html = markdown_to_html("- a\n- b\n  - b1\n  - b2\n- c\n\n1. one\n2. two\n")
    assert html == (
        "<ul><li>a</li><li>b<ul><li>b1</li><li>b2</li></ul></li><li>c</li></ul>"
        "<ol><li>one</li><li>two</li></ol>"
    )


def test_ordered_list_keeps_its_start_number() -> None:
    assert markdown_to_html("3. three\n4. four").startswith('<ol start="3">')


def test_blockquote_holds_paragraphs_and_inline_markup() -> None:
    html = markdown_to_html("> quoted **text**\n> more\n>\n> second")
    assert html == "<blockquote><p>quoted <strong>text</strong> more</p><p>second</p></blockquote>"


def test_fenced_code_block_is_kept_verbatim() -> None:
    html = markdown_to_html("Before\n\n```python\nif a < b:\n    print('x')\n```\n\nAfter")
    assert "<pre><code>if a &lt; b:\n    print(&#x27;x&#x27;)</code></pre>" in html
    assert html.startswith("<p>Before</p>") and html.endswith("<p>After</p>")


def test_unclosed_fence_runs_to_the_end() -> None:
    assert markdown_to_html("```\nabc\ndef").endswith("<pre><code>abc\ndef</code></pre>")


def test_simple_table() -> None:
    html = markdown_to_html("| Model | Score |\n| --- | ---: |\n| A | 0.91 |\n| B | **0.80** |\n")
    assert "<table>" in html and "<th>Model</th><th>Score</th>" in html
    assert "<td>A</td><td>0.91</td>" in html and "<td><strong>0.80</strong></td>" in html


def test_pipe_text_without_separator_row_is_a_paragraph() -> None:
    assert markdown_to_html("a | b | c").startswith("<p>a | b | c</p>")


def test_empty_input_gives_empty_output() -> None:
    assert markdown_to_html("") == "" and markdown_to_html("   \n\n") == ""
