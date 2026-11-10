# tests/test_brief_prompt.py
"""Contract-string tests for the Daily Brief narrative system prompt.

_SYSTEM is the stable system message the narrative LLM call sends. These tests pin the
prompt CONTRACT (not full behavior -- that's proven by the phase-end live smoke): the
[n] citation rule with an explicit bridging example, the 400-500 character bullet length,
the coverage clause (every featured article referenced), the consolidation clause (prefer
combining similar articles into one bullet), and representative humanizer-voice bans.
"""

from spyglass_service.brief_prompt import _SYSTEM


def test_system_states_the_bare_n_citation_rule_with_a_bridging_example():
    """The prompt must give a concrete example bridging the presented [#n] form to the
    cited [n] form, since item_block still renders articles as [#n] (the parser accepts
    both, but the instruction itself must tell the model to cite bare)."""
    assert "[#2]" in _SYSTEM
    assert "[2]" in _SYSTEM
    # Pin the literal bridging phrase so the assertion fails loudly if the prompt drifts
    # (a bare '[2]' presence check is vacuous -- '[2]' is a substring of '[#2]').
    assert "shown as [#2] is cited in a bullet as [2]" in _SYSTEM


def test_system_states_bullet_length_as_400_to_500_characters():
    """The old '2-4 sentences' rule is replaced by an explicit character range."""
    assert "400-500" in _SYSTEM
    assert "2-4 sentences" not in _SYSTEM


def test_system_states_a_coverage_clause():
    """Every featured article must be referenced at least once across the bullets."""
    lowered = _SYSTEM.lower()
    assert "every featured article" in lowered
    assert "at least once" in lowered


def test_system_states_a_consolidation_clause():
    """Prefer combining genuinely-similar articles into one bullet; split only when the
    point genuinely differs; never weld unrelated work together."""
    lowered = _SYSTEM.lower()
    assert "prefer combining" in lowered
    assert "never weld unrelated" in lowered


def test_system_states_the_lead_is_a_detailed_multi_sentence_overview():
    """The lead instruction expands from '2-3 sentences framing' to a fuller overview."""
    lowered = _SYSTEM.lower()
    assert "detailed" in lowered
    assert "multi-sentence" in lowered or "multi sentence" in lowered
    assert "2-3 sentences" not in _SYSTEM


def test_system_bans_em_and_en_dashes():
    """The humanizer voice contract explicitly bans em dashes and en dashes."""
    lowered = _SYSTEM.lower()
    assert "em dash" in lowered or "em-dash" in lowered
    assert "en dash" in lowered or "en-dash" in lowered


def test_system_bans_serves_as_style_verbs_in_favor_of_is_are():
    """Use 'is'/'are' plainly; ban 'serves as' / 'acts as' / 'functions as'."""
    lowered = _SYSTEM.lower()
    assert "serves as" in lowered
    assert "\"is\"" in lowered or "'is'" in lowered


def test_system_bans_significance_inflation_words():
    """No 'crucial', 'pivotal', 'game-changing', 'revolutionary'."""
    lowered = _SYSTEM.lower()
    assert "crucial" in lowered
    assert "pivotal" in lowered


def test_system_bans_ing_fake_depth_openers():
    """No 'Highlighting...' / 'Underscoring...' / 'Showcasing...' openers."""
    lowered = _SYSTEM.lower()
    assert "highlighting" in lowered
    assert "underscoring" in lowered or "showcasing" in lowered


def test_system_bans_rule_of_three_triads():
    """No rule-of-three triads."""
    assert "rule of three" in _SYSTEM.lower() or "rule-of-three" in _SYSTEM.lower()


def test_system_states_sentence_case_headings_with_a_word_cap():
    """Section headings: sentence case, plain text, at most ~8 words, no markdown, no [n]."""
    lowered = _SYSTEM.lower()
    assert "sentence case" in lowered
    assert "8 words" in lowered


def test_system_bans_bold_label_prefixes():
    """No '**label:**'-style bullet prefixes."""
    assert "**label:**" in _SYSTEM or "**label**" in _SYSTEM.lower()


def test_system_bans_filler_and_upbeat_wrap_ups():
    """Vary sentence length; no filler and no upbeat wrap-up conclusions."""
    lowered = _SYSTEM.lower()
    assert "vary" in lowered and "sentence length" in lowered
    assert "upbeat" in lowered


def test_system_keeps_existing_concrete_word_bans():
    """The pre-existing concrete AI-tell word bans are retained."""
    lowered = _SYSTEM.lower()
    for banned in (
        "delve", "moreover", "notably", "furthermore", "leverage",
        "in the realm of", "gains momentum", "it's worth noting",
        "plays a crucial role",
    ):
        assert banned in lowered, f"expected retained ban: {banned!r}"
    assert "stacked" in lowered and ("em-dash" in lowered or "em dash" in lowered)


def test_system_still_carries_the_schema_contract_shape():
    """The lead/sections/bullets contract shape is still described (schema itself unchanged)."""
    lowered = _SYSTEM.lower()
    assert "lead" in lowered
    assert "section" in lowered
    assert "bullet" in lowered


def test_system_interpolates_interest_once_at_the_end():
    """USER INTEREST STATEMENT stays the trailing, single interpolation point."""
    assert _SYSTEM.strip().endswith("USER INTEREST STATEMENT:\n{interest}")
    formatted = _SYSTEM.format(interest="robotics and RL")
    assert "robotics and RL" in formatted
    assert "{interest}" not in formatted


# ---------------------------------------------------------------------------
# Each featured article maps to EXACTLY ONE bullet. The
# prompt must state the one-bullet-per-article contract, the group-and-cite-all
# rule, the never-two-bullets-per-article rule, the never-invent-a-bullet rule,
# and the single-article-single-bullet rule (no padding into a multi-section
# brief). These sit alongside the retained 400-500 / coverage / voice rules.
# ---------------------------------------------------------------------------


def test_system_states_exactly_one_bullet_per_featured_article():
    """Every featured article maps to exactly one bullet."""
    lowered = _SYSTEM.lower()
    assert "exactly one bullet" in lowered
    assert "every featured article" in lowered


def test_system_states_group_related_articles_and_cite_all_their_numbers():
    """Genuinely-related articles go into ONE bullet citing ALL their numbers."""
    lowered = _SYSTEM.lower()
    assert "one bullet" in lowered
    assert "cite all" in lowered  # cite ALL their numbers in that single bullet


def test_system_forbids_two_bullets_about_the_same_article():
    """Never write two bullets about the same article."""
    lowered = _SYSTEM.lower()
    assert "never" in lowered
    assert "two bullets about the same article" in lowered


def test_system_forbids_inventing_a_bullet_or_section_not_grounded_in_an_article():
    """Never invent a bullet or section not grounded in a specific featured article."""
    lowered = _SYSTEM.lower()
    assert "never invent a bullet" in lowered
    assert "grounded in a specific" in lowered


def test_system_states_single_article_day_is_a_single_bullet():
    """A single-article day is a single bullet, not padded into a multi-section brief."""
    lowered = _SYSTEM.lower()
    assert "single article" in lowered or "one article" in lowered
    assert "single bullet" in lowered
    assert "multi-section" in lowered or "multiple sections" in lowered
