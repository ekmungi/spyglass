# tests/test_brief_render.py
"""Tests for brief_render.py: token substitution + markdown assembly.

The _REF_TOKEN pattern must match both [n] and [#n] forms so LLM-written bare [n]
tokens are substituted just like the canonical [#n] form.
"""

from spyglass_service.brief_render import Bullet, FeaturedEntry, render_brief_markdown, replace_refs


def _entries() -> list[FeaturedEntry]:
    """Two featured entries so [1]/[#1] and [2]/[#2] both resolve."""
    return [
        FeaturedEntry(card_id=10, title="Article One", origin="Source A",
                      published="2026-07-01", level="high"),
        FeaturedEntry(card_id=20, title="Article Two", origin="Source B",
                      published="2026-07-02", level="medium"),
    ]


def test_replace_refs_substitutes_bare_ref_token():
    """Bare [2] without the # is substituted into the correct card link."""
    entries = _entries()
    narrative = "Check out [2] for details."
    result = replace_refs(narrative, entries)
    assert result == "Check out [Article Two](card:20) for details."
    assert "[2]" not in result


def test_replace_refs_still_substitutes_canonical_hash_ref_token():
    """The canonical [#2] form still works (regression guard)."""
    entries = _entries()
    narrative = "See [#2] for more info."
    result = replace_refs(narrative, entries)
    assert result == "See [Article Two](card:20) for more info."
    assert "[#2]" not in result


def test_replace_refs_leaves_out_of_range_bare_tokens_verbatim():
    """Out-of-range bare [99] is left untouched (no entry #99 -> no substitution)."""
    entries = _entries()
    narrative = "Bad ref [99] stays as is."
    result = replace_refs(narrative, entries)
    assert "[99]" in result
    assert result == "Bad ref [99] stays as is."


def test_replace_refs_mixes_bare_and_hash_forms():
    """A narrative using both [1] and [#2] forms substitutes both correctly."""
    entries = _entries()
    narrative = "Start with [1], then [#2]."
    result = replace_refs(narrative, entries)
    assert result == "Start with [Article One](card:10), then [Article Two](card:20)."
    assert "[1]" not in result and "[#2]" not in result


def test_render_brief_markdown_flattens_embedded_newline_in_bullet_text():
    """A bullet whose LLM-written text contains a hard newline must render as ONE
    physical markdown line (parser contract).

    The frontend parser (briefBullets.ts parseBriefBullets) treats each physical
    line as a unit: a top-level '- ' line is a bullet, anything else is ignored.
    If the backend ever emits a bare column-0 continuation line, the frontend
    silently drops it -- truncating the bullet and losing any card ref that
    happened to live on the continuation line. The renderer must flatten
    embedded newlines in bullet.text before substitution so this can't happen.
    """
    entries = _entries()
    bullet = Bullet(text="First part of the bullet\nsecond part cites [1].", related=[])
    markdown = render_brief_markdown("Lead.", [("Heading", [bullet])], [entries[0]], [])

    # Isolate the 'Heading' section from the (unrelated) References section --
    # both render '- ' lines, and only the Heading section's bullet is under test.
    section = markdown.split("## Heading", 1)[1].split("## References", 1)[0]
    lines = section.split("\n")
    bullet_lines = [line for line in lines if line.startswith("- ")]
    assert len(bullet_lines) == 1, f"expected exactly one bullet line, got {bullet_lines}"
    rendered = bullet_lines[0]

    # Both halves of the original text must survive, joined by a space (not a newline).
    assert "First part of the bullet" in rendered
    assert "second part" in rendered
    assert "\n" not in rendered

    # The [1] token on the (former) continuation line must still substitute to the
    # card link -- this is the "dropped card ref" symptom the bug produces.
    assert "[Article One](card:10)" in rendered

    # No line anywhere in the output is a bare orphaned continuation line.
    assert not any(line.strip().startswith("second part") for line in lines)


def test_render_brief_markdown_normalizes_dashes_in_prose_but_preserves_title_dashes():
    """Deterministic render-layer backstop for the humanizer voice contract.

    The LLM bans em (--U+2014) and en (--U+2013) dashes in brief prose, but the
    prompt-only ban leaks ~2 em-dashes per brief in live smoke. The renderer must strip
    U+2014/U+2013 from LLM-authored prose (lead, heading, bullet text) BEFORE replace_refs
    substitutes card links -- so a real card title containing a legitimate dash (e.g. an
    arXiv paper "Vision-Language Model") is preserved intact, only the LLM's own prose is
    scrubbed. The renderer's own structural "-- {origin}" separator in the References line
    is deliberate formatting, not LLM voice, and must survive untouched.
    """
    lead = "AI in medicine advances — from CT to ultrasound."
    heading = "Diagnostics – imaging breakthroughs"
    bullet = Bullet(text="New model beats radiologists — cites [1].", related=[])
    entry = FeaturedEntry(
        card_id=1,
        title="Vision–Language Model",
        origin="Source A",
        published="2026-07-01",
        level="high",
    )

    markdown = render_brief_markdown(lead, [(heading, [bullet])], [entry], [])

    lead_line = markdown.split("\n\n", 1)[0]
    section = markdown.split("## References", 1)[0]
    references = markdown.split("## References", 1)[1]

    # 1. Narrative prose (lead, heading, bullet) has no em or en dash left.
    assert "—" not in lead_line
    assert "–" not in lead_line
    heading_line = next(line for line in section.split("\n") if line.startswith("## "))
    assert "—" not in heading_line
    assert "–" not in heading_line
    # The bullet line legitimately contains a dash from the substituted card-link title
    # (checked separately below) -- strip that substring before checking the LLM's own
    # prose is dash-free, so the two concerns aren't conflated.
    bullet_line = next(line for line in section.split("\n") if line.startswith("- "))
    bullet_prose_only = bullet_line.replace("[Vision–Language Model](card:1)", "")
    assert "—" not in bullet_prose_only
    assert "–" not in bullet_prose_only

    # 2. The featured entry's title dash is preserved intact in its card link.
    assert "[Vision–Language Model](card:1)" in markdown

    # 3. The renderer's own structural em-dash in the References line survives untouched.
    assert "—" in references
