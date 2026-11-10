# tests/test_enrich_prompt.py -- Tests for the enrichment contract.
from spyglass_service.enrich_prompt import (
    build_messages, enrich_schema, parse_enrichment, bucket_from_score, EnrichmentResult)

def test_interest_statement_is_in_stable_prefix():
    msgs = build_messages("AI in healthcare", "Title", "Body text", full=True)
    assert msgs[0]["role"] == "system"
    assert "AI in healthcare" in msgs[0]["content"]   # interest in the cacheable prefix
    assert "Body text" in msgs[-1]["content"]          # article last

def test_blurb_mode_omits_full_text_marker():
    full = build_messages("i", "T", "B", full=True)[-1]["content"]
    blurb = build_messages("i", "T", "B", full=False)[-1]["content"]
    assert "full text" in full.lower()
    assert "full text" not in blurb.lower()

def test_parse_enrichment_roundtrip():
    r = parse_enrichment({"relevance_score": 82, "relevance_reason": "match",
                          "summary": "s", "tags": ["a", "b"], "category": "AI",
                          "fits": True, "confidence": 0.9})
    assert isinstance(r, EnrichmentResult)
    assert r.relevance_score == 82 and r.tags == ["a", "b"] and r.fits is True

def test_parse_clamps_score_and_defaults():
    r = parse_enrichment({"relevance_score": 150, "summary": "s"})
    assert r.relevance_score == 100
    assert r.tags == [] and r.fits is False and r.relevance_reason == ""

def test_bucket_from_score():
    assert bucket_from_score(80) == "high"
    assert bucket_from_score(50) == "medium"
    assert bucket_from_score(20) == "low"
    assert bucket_from_score(5) == "out"


def test_system_prompt_conveys_summary_length_target():
    """Reader summaries were skewing too short (bare 'concise' with no target). The system
    prompt must now steer the model toward a ~350-400 char summary (max ~450) so enrichment
    produces a meatier, more useful reader summary."""
    sys = build_messages("i", "T", "B", full=True)[0]["content"]
    assert "350-400" in sys
    assert "characters" in sys.lower()


# --- closed-vocabulary category assignment ---

def test_enrich_schema_constrains_category_to_the_given_enum():
    """With a category set, the schema's `category` is an enum over exactly that set + null,
    so the model cannot coin a new label."""
    schema = enrich_schema(["Healthcare AI", "Robotics"])["schema"]
    cat = schema["properties"]["category"]
    assert set(cat["enum"]) == {"Healthcare AI", "Robotics", None}

def test_enrich_schema_empty_set_allows_only_null():
    """No categories yet -> nothing to assign; category can only be null (Unsorted)."""
    cat = enrich_schema([])["schema"]["properties"]["category"]
    assert cat["enum"] == [None]

def test_build_messages_lists_the_categories_for_the_model():
    """The category set is shown to the model (not just hinted at) so it picks from it."""
    sys = build_messages("i", "T", "B", full=True,
                         categories=["Healthcare AI", "Robotics"])[0]["content"]
    assert "Healthcare AI" in sys and "Robotics" in sys

def test_parse_enrichment_maps_a_stray_category_to_unsorted():
    """Post-validation backstop: a category outside the allowed set becomes None (Unsorted),
    even if the model ignored the enum."""
    r = parse_enrichment(
        {"relevance_score": 80, "summary": "s", "category": "Made Up Label", "fits": True},
        allowed={"Healthcare AI", "Robotics"},
    )
    assert r.category is None

def test_parse_enrichment_keeps_an_allowed_category():
    r = parse_enrichment(
        {"relevance_score": 80, "summary": "s", "category": "Robotics", "fits": True},
        allowed={"Healthcare AI", "Robotics"},
    )
    assert r.category == "Robotics"

def test_parse_enrichment_without_allowed_is_unconstrained():
    """Back-compat: no allowed set -> category passes through as before."""
    r = parse_enrichment(
        {"relevance_score": 80, "summary": "s", "category": "Anything", "fits": True}
    )
    assert r.category == "Anything"
