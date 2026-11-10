# tests/test_brief_narrative.py
"""Tests for the structured Daily Brief narrative.

The LLM returns {lead, sections: [{heading, bullets: [str]}]}: each section is a set of
grouped bullets, not one prose body. The schema/prompt carry the grouping + voice
rules, parse_brief_payload rejects anything malformed (pause semantics), and the renderer
emits lead + '## heading' + one '- ' item per bullet, with [#n] -> card-link substitution
across the lead and every bullet.
"""

import pytest

from spyglass_service.brief_narrative import BriefComposeError, parse_brief_payload
from spyglass_service.brief_prompt import BRIEF_SCHEMA, build_brief_messages
from spyglass_service.brief_render import Bullet, FeaturedEntry, render_brief_markdown

# ---------------------------------------------------------------------------
# Schema + prompt contract
# ---------------------------------------------------------------------------


def test_brief_schema_requires_lead_and_sections_of_bullets():
    """The structured-output schema demands a lead string and sections of bullet lists."""
    schema = BRIEF_SCHEMA["schema"]
    assert set(schema["required"]) == {"lead", "sections"}
    assert schema["properties"]["lead"]["type"] == "string"
    sections = schema["properties"]["sections"]
    assert sections["type"] == "array"
    assert sections["minItems"] == 1
    item = sections["items"]
    assert set(item["required"]) == {"heading", "bullets"}
    assert item["properties"]["heading"]["type"] == "string"
    bullets = item["properties"]["bullets"]
    assert bullets["type"] == "array"
    assert bullets["minItems"] == 1
    assert bullets["items"]["type"] == "string"


def test_brief_messages_carry_the_grouping_and_voice_rules():
    """The system message states the bullet-grouping + humanizer-voice rules."""
    messages = build_brief_messages("robotics and RL", ["[#1] T — S"])
    system = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert "bullet" in system.lower()
    assert "group" in system.lower()  # group related articles into one bullet
    assert "prefer combining" in system.lower()  # lean toward combining, not splitting
    assert "at least once" in system.lower()  # every featured article referenced
    assert "underscore" in system.lower()  # the banned-AI-tells list is present
    assert "robotics and RL" in system  # the interest profile rides the stable prefix
    assert messages[1]["content"].startswith("FEATURED ARTICLES:")
    assert "[#1] T" in messages[1]["content"]


# ---------------------------------------------------------------------------
# parse_brief_payload: strict validation, malformed -> BriefComposeError
# ---------------------------------------------------------------------------


def test_parse_brief_payload_accepts_a_well_formed_payload():
    """A valid payload yields the lead and (heading, [bullets]) tuples in order."""
    lead, sections = parse_brief_payload(
        {
            "lead": "A quiet day.",
            "sections": [
                {"heading": "Robotics", "bullets": ["See [#1].", "Also [#2]."]},
                {"heading": "Models", "bullets": ["Then [#3]."]},
            ],
        }
    )
    assert lead == "A quiet day."
    assert sections == [
        ("Robotics", ["See [#1].", "Also [#2]."]),
        ("Models", ["Then [#3]."]),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nothing at all
        {"lead": "ok"},  # sections missing
        {"sections": [{"heading": "h", "bullets": ["b"]}]},  # lead missing
        {"lead": None, "sections": [{"heading": "h", "bullets": ["b"]}]},  # lead null
        {"lead": "   ", "sections": [{"heading": "h", "bullets": ["b"]}]},  # lead blank
        {"lead": "ok", "sections": []},  # sections empty
        {"lead": "ok", "sections": "not-a-list"},  # sections wrong type
        {"lead": "ok", "sections": ["not-a-dict"]},  # section wrong type
        {"lead": "ok", "sections": [{"bullets": ["b"]}]},  # heading missing
        {"lead": "ok", "sections": [{"heading": "", "bullets": ["b"]}]},  # heading blank
        {"lead": "ok", "sections": [{"heading": "h"}]},  # bullets missing
        {"lead": "ok", "sections": [{"heading": "h", "bullets": []}]},  # bullets empty
        {"lead": "ok", "sections": [{"heading": "h", "bullets": "b"}]},  # bullets not a list
        {"lead": "ok", "sections": [{"heading": "h", "bullets": ["  "]}]},  # bullet blank
        {"lead": "ok", "sections": [{"heading": "h", "bullets": [3]}]},  # bullet non-string
        {"lead": "ok", "sections": [{"heading": 3, "bullets": ["b"]}]},  # heading non-string
    ],
)
def test_parse_brief_payload_rejects_malformed_payloads(payload):
    """Anything short of the full contract raises BriefComposeError (pause, write nothing)."""
    with pytest.raises(BriefComposeError):
        parse_brief_payload(payload)


# ---------------------------------------------------------------------------
# Rendering: lead paragraph, then '## heading' + one '- ' bullet per bullet
# ---------------------------------------------------------------------------


def _entries() -> list[FeaturedEntry]:
    """Two featured entries so [#1]/[#2] both resolve."""
    return [
        FeaturedEntry(card_id=11, title="Story A", origin="Blog", published="2026-07-01",
                      level="high"),
        FeaturedEntry(card_id=12, title="Story B", origin="Wire", published="2026-07-02",
                      level="medium"),
    ]


def test_render_emits_lead_then_section_headings_and_bullets():
    """The lead comes first; each section renders as '## heading' + one '- ' per bullet."""
    md = render_brief_markdown(
        "The day in one line about [#1].",
        [("Robots on the move", [Bullet("First point [#1]."), Bullet("Second point [#2].")])],
        _entries(),
        [],
    )
    assert md.startswith("The day in one line about [Story A](card:11).")
    assert "## Robots on the move\n\n- First point [Story A](card:11)." in md
    # Each bullet is its own list item.
    assert "- Second point [Story B](card:12)." in md
    # References still follow the sections.
    assert md.index("## Robots on the move") < md.index("## References")


def test_render_substitutes_refs_across_lead_and_every_bullet():
    """[#n] substitution covers the lead and all bullets; out-of-range stays put."""
    md = render_brief_markdown(
        "Lead cites [#2].",
        [("One", [Bullet("Bullet cites [#1].")]), ("Two", [Bullet("Bad token [#9] survives.")])],
        _entries(),
        [],
    )
    assert "Lead cites [Story B](card:12)." in md
    assert "- Bullet cites [Story A](card:11)." in md
    assert "[#9]" in md  # never invent a link for a hallucinated number


def test_render_emits_inline_related_subline_when_a_bullet_has_related():
    """A bullet with inline related items gets an indented '  - Related:' sub-line."""
    md = render_brief_markdown(
        "Lead.",
        [("Theme", [Bullet("Point [#1].", related=[("Neighbour X", 91), ("Neighbour Y", 92)])])],
        _entries(),
        [],
    )
    assert "- Point [Story A](card:11)." in md
    assert "  - Related: [Neighbour X](card:91), [Neighbour Y](card:92)" in md


def test_render_omits_inline_related_when_a_bullet_has_none():
    """A bullet with no related items renders no 'Related:' sub-line at all."""
    md = render_brief_markdown(
        "Lead.",
        [("Theme", [Bullet("Point [#1].", related=[])])],
        _entries(),
        [],
    )
    assert "- Point [Story A](card:11)." in md
    assert "Related:" not in md


def test_render_listed_only_uses_fixed_lead_and_zero_sections():
    """The deterministic no-featured path: fixed lead line, no section headings."""
    from spyglass_service.brief_narrative import NO_FEATURED_LEAD

    md = render_brief_markdown(NO_FEATURED_LEAD, [], [], [("Tail item", 5)])
    assert md.startswith(NO_FEATURED_LEAD)
    assert "## References" not in md  # no featured entries
    assert "## Also noticed\n- [Tail item](card:5)" in md
    # The only heading is Also noticed -- no thematic sections were rendered.
    assert md.count("## ") == 1


# ---------------------------------------------------------------------------
# Inline related selection: exclude brief cards, threshold, dedupe
# ---------------------------------------------------------------------------


def _norm_bytes(vec: list[float]):
    """A normalized float32 vector's bytes, ready for EmbeddingIndex.add."""
    import numpy as np

    v = np.array(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).tobytes()


def _seed_related_fixture(tmp_path):
    """Engine + index with four items around item 1: a close in-brief neighbour, a close
    NOT-in-brief neighbour, and a far one below the threshold."""
    import numpy as np
    from sqlmodel import Session

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.embeddings import EmbeddingIndex
    from spyglass_service.models import Card, Item

    engine = create_db_engine(tmp_path / "rel.db")
    init_db(engine)
    index = EmbeddingIndex(lambda t: np.ones((len(t), 4), np.float32), "fake", 4)
    index.add(1, _norm_bytes([1, 0, 0, 0]))        # the bullet's featured article (in brief)
    index.add(2, _norm_bytes([0.9, 0.4359, 0, 0]))  # cosine ~0.9 -> related, NOT in brief
    index.add(3, _norm_bytes([0.8, 0.6, 0, 0]))     # cosine 0.8 but IS in the brief -> excluded
    index.add(4, _norm_bytes([0, 0, 1, 0]))         # cosine 0 -> below threshold, dropped
    import datetime as _dt

    judged = _dt.datetime(2026, 7, 2, tzinfo=_dt.UTC)
    labels = {1: "Featured F", 2: "Related R", 3: "Brief B", 4: "Far N"}
    with Session(engine) as s:
        for iid, title in labels.items():
            s.add(Item(id=iid, source="t", external_id=str(iid), title=title,
                       url=f"https://x.test/{iid}"))
            s.flush()
            # Judged high so the non-out inline-related filter keeps a qualifying neighbour.
            s.add(Card(id=iid, item_id=iid, summary="s", relevance_score=85, relevance_at=judged))
        s.commit()
    return engine, index


def test_inline_related_excludes_brief_cards_and_below_threshold(tmp_path):
    """The related sub-line keeps only close corpus neighbours NOT already in the brief."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import _inline_related_for_bullet

    engine, index = _seed_related_fixture(tmp_path)
    with Session(engine) as s:
        related = _inline_related_for_bullet(
            engine, s, index, item_ids=[1], exclude_card_ids={1, 3}, already_shown=set(),
        )
    assert related == [("Related R", 2)]  # B is in the brief, N is below threshold


def test_inline_related_dedupes_within_a_section(tmp_path):
    """already_shown carries across a section's bullets so a neighbour surfaces once."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import _inline_related_for_bullet

    engine, index = _seed_related_fixture(tmp_path)
    with Session(engine) as s:
        shown: set[int] = set()
        first = _inline_related_for_bullet(engine, s, index, [1], {1, 3}, shown)
        second = _inline_related_for_bullet(engine, s, index, [1], {1, 3}, shown)
    assert first == [("Related R", 2)]
    assert second == []  # R was already shown earlier in the section


# ---------------------------------------------------------------------------
# _build_bullets: ref token extraction (bare [n] support)
# ---------------------------------------------------------------------------


def test_ref_token_matches_both_bare_and_hash_forms():
    """Verify the _REF_TOKEN pattern matches both [n] and [#n] forms."""
    from spyglass_service.brief_render import _REF_TOKEN

    # Bare [n] form should match and capture the digit.
    bare_match = _REF_TOKEN.search("See [1] for info.")
    assert bare_match is not None
    assert bare_match.group(1) == "1"

    # Hash [#n] form should still match and capture the digit (regression guard).
    hash_match = _REF_TOKEN.search("See [#2] for info.")
    assert hash_match is not None
    assert hash_match.group(1) == "2"

    # Both forms in the same text.
    both_text = "Check [1] and [#2]."
    all_matches = _REF_TOKEN.findall(both_text)
    assert set(all_matches) == {"1", "2"}

    # Out-of-range numbers are still matched.
    out_match = _REF_TOKEN.search("[99]")
    assert out_match is not None
    assert out_match.group(1) == "99"


def test_narrative_assembly_substitutes_a_bare_ref_and_attaches_related(tmp_path):
    """A bare [1] bullet flows through real assembly: inline card link + Related.

    This exercises the bare [1] form end-to-end: narrative_and_markdown substitutes it
    into the featured entry's card link AND its close corpus neighbour surfaces as Related.
    """
    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    # LLM stub: one section whose bullet cites a BARE [1] (no #), the bare form.
    def llm(messages):
        return {"lead": "Lead.", "sections": [{"heading": "Theme",
                "bullets": ["New work on X as [1] shows."]}]}

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    # Keep the session open through the render call so the (Card, Item) attributes stay
    # loaded (the compose path passes freshly-read rows the same way).
    with Session(engine) as s:
        # Feature item 1 (the bullet's article); item 2 is its close neighbour NOT in the
        # brief, so it must appear on the inline Related line.
        featured = [(s.get(Card, 1), s.get(Item, 1))]
        listed: list[tuple[Card, Item]] = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)
    # The bare [1] was substituted into the featured card's inline link (card id 1).
    assert "New work on X as [Featured F](card:1) shows." in markdown
    assert "[1] shows" not in markdown  # the bare token no longer survives verbatim
    # The bullet's close corpus neighbour (item 2) surfaced as an inline Related link.
    assert "  - Related: [Related R](card:2)" in markdown


# ---------------------------------------------------------------------------
# Resolvable-ref validation gate (now subsumed by the partition gate below): a featured
# brief whose bullets carry no resolvable [n]/[#n] reference must pause (raise
# BriefComposeError) rather than persist a reference-less brief. The partition gate
# strengthens this from "at least one resolvable ref anywhere" to a full
# one-bullet-per-featured-card partition.
# ---------------------------------------------------------------------------


def test_narrative_raises_when_no_bullet_carries_a_resolvable_ref(tmp_path):
    """Featured but zero resolvable refs across all bullets -> BriefComposeError, pause."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import BriefComposeError, narrative_and_markdown
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    # LLM stub: bullets carry no ref at all, and one out-of-range ref ([99]) -- neither
    # resolves against a single-item featured list (len(featured) == 1).
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["No reference here at all.", "Bad [99] ref."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = [(s.get(Card, 1), s.get(Item, 1))]
        listed: list[tuple[Card, Item]] = []
        # The partition gate subsumes the no-resolvable-ref case:
        # with a single featured item and zero resolvable refs, coverage of card 1 fails.
        with pytest.raises(BriefComposeError, match="coverage|cite"):
            narrative_and_markdown(engine, index, settings, featured, listed, llm)


def test_narrative_composes_when_a_bullet_carries_a_resolvable_ref(tmp_path):
    """Regression: a resolvable [n] in a clean single-bullet partition composes, no raise."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    # A single featured article -> a single bullet citing [1] (no dangling,
    # ref-less bullet; that is now a fabricated-bullet violation, tested separately).
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["Cites [1] directly."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = [(s.get(Card, 1), s.get(Item, 1))]
        listed: list[tuple[Card, Item]] = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)
    assert "Cites [Featured F](card:1) directly." in markdown


def test_narrative_reference_date_uses_local_day_not_raw_utc_date(tmp_path):
    """The References line's date comes from local_day(card, item),
    not the old raw (item.published_at or card.created_at).date().isoformat().

    Sets a late-UTC published_at (23:30 UTC) that can roll to a different calendar date
    once converted to a local timezone with a positive offset. Rather than hardcode a
    specific local timezone (the production call site omits tz/today, so it uses whatever
    timezone the test machine runs in), this asserts the rendered date equals
    local_day(card, item) computed the same way production does -- proving the display
    line is now driven by the helper, deterministically, regardless of machine tz.
    """
    from datetime import UTC, datetime

    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.brief_time import local_day
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    # Push item 1's publish time late in the UTC day so a positive-offset local
    # timezone would roll it to the next calendar day -- the scenario the old raw
    # UTC-date logic could not express.
    late_utc = datetime(2026, 7, 5, 23, 30, tzinfo=UTC).replace(tzinfo=None)
    with Session(engine) as s:
        item = s.get(Item, 1)
        item.published_at = late_utc
        s.add(item)
        s.commit()

    def llm(messages):
        return {"lead": "Lead.", "sections": [{"heading": "Theme", "bullets": ["Cites [1] directly."]}]}

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        card = s.get(Card, 1)
        item = s.get(Item, 1)
        expected_day = local_day(card, item)  # same call signature the production code uses
        featured = [(card, item)]
        listed: list[tuple[Card, Item]] = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)

    assert f"[Featured F](card:1) — t, {expected_day.isoformat()}, high" in markdown


def test_narrative_gate_does_not_fire_on_featured_empty_listed_only_path(tmp_path):
    """The listed-only (featured-empty) path sets sections=[] and must NOT trigger the gate."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import NO_FEATURED_LEAD, narrative_and_markdown
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured: list[tuple[Card, Item]] = []
        listed = [(s.get(Card, 4), s.get(Item, 4))]
        # llm=None would attempt a real call, but featured is empty so the LLM is never invoked.
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, None)
    assert markdown.startswith(NO_FEATURED_LEAD)


# ---------------------------------------------------------------------------
# Partition validation gate: each featured card is the
# main source of EXACTLY ONE bullet. The resolvable-ref check is
# widened into a full partition gate over the featured numbers cited across
# the bullets. A featured brief must satisfy ALL of:
#   (a) no featured number cited in >=2 bullets (no duplication),
#   (b) every featured number 1..N cited in exactly one bullet (full coverage),
#   (c) every bullet cites >=1 featured number (no fabricated bullet).
# Any violation raises BriefComposeError (pause -- nothing is written). Only
# fires when featured is non-empty; the listed-only path is unaffected.
# ---------------------------------------------------------------------------


def _two_featured(s):
    """Featured (Card, Item) pairs for items 1 and 2 -> tokens [1] and [2]."""
    from spyglass_service.models import Card, Item

    return [(s.get(Card, 1), s.get(Item, 1)), (s.get(Card, 2), s.get(Item, 2))]


def test_partition_gate_raises_when_a_featured_number_is_cited_in_two_bullets(tmp_path):
    """(a) A featured number cited in two bullets duplicates its card -> pause."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import BriefComposeError, narrative_and_markdown
    from spyglass_service.config import Settings

    engine, index = _seed_related_fixture(tmp_path)

    # [1] appears in TWO bullets (over-split), [2] appears once. Duplication of card 1.
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["First take on [1].", "Second take on [1]."]},
                {"heading": "Other", "bullets": ["A point on [2]."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = _two_featured(s)
        listed: list = []
        with pytest.raises(BriefComposeError, match="duplicat"):
            narrative_and_markdown(engine, index, settings, featured, listed, llm)


def test_partition_gate_raises_when_a_featured_number_is_never_cited(tmp_path):
    """(b) A featured item left uncited breaks full coverage -> pause."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import BriefComposeError, narrative_and_markdown
    from spyglass_service.config import Settings

    engine, index = _seed_related_fixture(tmp_path)

    # Only [1] is cited; [2] never appears -> card 2 dropped from the brief.
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [{"heading": "Theme", "bullets": ["Only a point on [1]."]}],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = _two_featured(s)
        listed: list = []
        with pytest.raises(BriefComposeError, match="coverage"):
            narrative_and_markdown(engine, index, settings, featured, listed, llm)


def test_partition_gate_raises_when_a_bullet_cites_no_featured_number(tmp_path):
    """(c) A bullet citing no featured number is a fabricated bullet -> pause."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import BriefComposeError, narrative_and_markdown
    from spyglass_service.config import Settings

    engine, index = _seed_related_fixture(tmp_path)

    # Both [1] and [2] are covered (once each), but a THIRD bullet cites nothing
    # resolvable -- an invented bullet not grounded in any featured article.
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["A point on [1].", "A point on [2]."]},
                {"heading": "Invented", "bullets": ["A vibes bullet with no article."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = _two_featured(s)
        listed: list = []
        with pytest.raises(BriefComposeError, match="cite"):
            narrative_and_markdown(engine, index, settings, featured, listed, llm)


def test_partition_gate_passes_on_a_clean_one_bullet_per_card_partition(tmp_path):
    """A clean partition (each featured number cited in exactly one bullet) renders."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.config import Settings

    engine, index = _seed_related_fixture(tmp_path)

    # [1] in one bullet, [2] in another -- exactly one bullet per featured card.
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["A point on [1]."]},
                {"heading": "Other", "bullets": ["A point on [2]."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = _two_featured(s)
        listed: list = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)
    assert "A point on [Featured F](card:1)." in markdown
    assert "A point on [Related R](card:2)." in markdown


def test_partition_gate_allows_a_grouped_bullet_citing_several_featured_numbers(tmp_path):
    """A single bullet may cite MULTIPLE featured numbers (grouping); still one bullet each."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.config import Settings

    engine, index = _seed_related_fixture(tmp_path)

    # One grouped bullet cites BOTH [1] and [2]. Each number still appears in exactly
    # one bullet -- grouping related articles is the desired behaviour, not a violation.
    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [
                {"heading": "Theme", "bullets": ["Related work in [1] and [2] together."]},
            ],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = _two_featured(s)
        listed: list = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)
    assert "[Featured F](card:1)" in markdown
    assert "[Related R](card:2)" in markdown


def test_partition_gate_passes_single_article_single_bullet(tmp_path):
    """A single-article day is a single bullet citing [1]."""
    from sqlmodel import Session

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.config import Settings
    from spyglass_service.models import Card, Item

    engine, index = _seed_related_fixture(tmp_path)

    def llm(messages):
        return {
            "lead": "Lead.",
            "sections": [{"heading": "Theme", "bullets": ["The one story today is [1]."]}],
        }

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as s:
        featured = [(s.get(Card, 1), s.get(Item, 1))]
        listed: list = []
        markdown = narrative_and_markdown(engine, index, settings, featured, listed, llm)
    assert "The one story today is [Featured F](card:1)." in markdown
