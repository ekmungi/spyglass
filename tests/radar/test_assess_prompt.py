"""Tests for the assessment prompts, schemas, reply parsing and the tier rule."""

import json

import pytest

from spyglass_service.radar.assess_prompt import (
    RUBRIC,
    TEXT_CHARS,
    build_digest_messages,
    build_triage_messages,
    clean_snippet,
    digest_schema,
    parse_digest,
    parse_triage,
    plain_title,
    slugify,
    tier_for,
    triage_row,
    triage_schema,
)
from spyglass_service.radar.models import KINDS

KEYS = ["models", "health"]


@pytest.mark.parametrize(("score", "from_user", "tier"), [
    (100, False, "top"), (80, False, "top"), (79, False, "notable"), (60, False, "notable"),
    (59, False, "skim"), (45, False, "skim"), (44, False, "out"), (0, False, "out"),
    (90, True, "top"), (50, True, "notable"), (0, True, "notable"),
])
def test_tier_for_maps_scores_and_floors_reader_items(score: int, from_user: bool, tier: str) -> None:
    """Score bands map to tiers; an item the reader sent in never falls below notable."""
    assert tier_for(score, from_user=from_user) == tier


def test_triage_schema_constrains_section_and_kind() -> None:
    """The section enum is the profile's keys plus empty; kind is the fixed list."""
    row = triage_schema(KEYS)["schema"]["properties"]["items"]["items"]
    assert row["properties"]["section"]["enum"] == ["models", "health", ""]
    assert row["properties"]["kind"]["enum"] == list(KINDS)
    assert set(row["required"]) == {"id", "reason", "score", "section", "kind"}


def test_digest_schema_requires_every_field() -> None:
    """A strict schema needs every property listed as required."""
    schema = digest_schema(KEYS)["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_clean_snippet_strips_markup_and_arxiv_prefix() -> None:
    """HTML tags, entities and the arXiv announcement prefix are removed; text is cut."""
    raw = "arXiv:2607.01234v1 Announce Type: new Abstract: <p>We &amp; they</p> " + "x" * 400
    out = clean_snippet(raw, limit=20)
    assert out.startswith("We & they")
    assert out.endswith("…") and len(out) <= 21
    assert clean_snippet(None) == ""


@pytest.mark.parametrize(("raw", "plain"), [
    ('<a href="https://x.org/a">Payer &amp; AI deal</a>', "Payer & AI deal"),
    ('Carelon agrees <a href="https://www.example.org/payers/carel', "Carelon agrees"),
    ("<br>", "<br>"),
    (None, ""),
])
def test_plain_title_strips_markup(raw: str | None, plain: str) -> None:
    """Complete and cut-off tags are removed; a title that is only markup is kept raw."""
    assert plain_title(raw) == plain


def test_triage_messages_put_profile_in_system_and_items_in_user() -> None:
    """The stable rubric and profile lead; each item is one JSON line in the user message."""
    rows = [triage_row(7, "  A   title ", "Pub", "rss", "<b>body</b>")]
    messages = build_triage_messages("PROFILE BLOCK", rows)
    assert messages[0]["content"].startswith(RUBRIC[:40])
    assert "PROFILE BLOCK" in messages[0]["content"]
    line = json.loads(messages[1]["content"].splitlines()[1])
    assert line == {"id": 7, "title": "A title", "publication": "Pub", "source": "rss",
                    "text": "body"}


def test_digest_messages_cap_the_text() -> None:
    """The digest reads at most TEXT_CHARS of the article."""
    messages = build_digest_messages("P", {"title": "T", "url": "u"}, "y" * (TEXT_CHARS + 500))
    assert messages[1]["content"].count("y") == TEXT_CHARS


def test_parse_triage_keeps_good_rows_and_reports_bad_ones() -> None:
    """Valid rows parse and clamp; missing, malformed, unknown and duplicate rows are handled."""
    raw = {"items": [
        {"id": 1, "score": 140, "section": "HEALTH", "kind": "paper"},
        {"id": 2, "score": "high", "section": "health", "kind": "news"},
        {"id": 9, "score": 50, "section": "health", "kind": "news"},
        {"id": 1, "score": 10, "section": "models", "kind": "news"},
        {"id": 3, "score": 55.6, "section": "nonsense", "kind": "weird"},
    ]}
    results, bad = parse_triage(raw, [1, 2, 3, 4], KEYS)
    assert results[1].score == 100 and results[1].section == "health" and results[1].kind == "paper"
    assert results[3].score == 56 and results[3].section == "" and results[3].kind == "news"
    assert bad == [2, 4]


def test_parse_triage_treats_a_non_object_reply_as_all_bad() -> None:
    """A reply that is not the expected object leaves every id unjudged."""
    assert parse_triage(["nope"], [1, 2], KEYS) == ({}, [1, 2])
    assert parse_triage({"items": "x"}, [5], KEYS) == ({}, [5])


def test_parse_digest_cleans_fields() -> None:
    """Headline is capped, lists are de-duplicated and capped, event key is slugged."""
    raw = {"headline": " ".join(["word"] * 20), "why": "  You  can act. ", "score": 72,
           "key_points": ["a", "a", "b", "c", "d", "e"], "entities": ["X", ""],
           "event_key": "OpenAI GPT-6 Release!", "section": "models", "kind": "release"}
    result = parse_digest(raw, KEYS)
    assert len(result.headline.split()) == 12
    assert result.why == "You can act."
    assert result.key_points == ("a", "b", "c", "d")
    assert result.entities == ("X",)
    assert result.event_key == "openai-gpt-6-release"


@pytest.mark.parametrize(("raw", "clean"), [
    ("Lab ships a model.", "Lab ships a model"),
    ("Shattered compares local coding models gpt-oss, Gemma 4 and Kimi on hardware, memory "
     "and licences", "Shattered compares local coding models gpt-oss, Gemma 4 and Kimi on hardware"),
    ("A headline of exactly fourteen words stays whole even though it is long",
     "A headline of exactly fourteen words stays whole even though it is long"),
])
def test_parse_digest_tidies_headline_endings(raw: str, clean: str) -> None:
    """Trailing full stops go; a cut headline never ends on a comma."""
    assert parse_digest({"headline": raw, "score": 60}, KEYS).headline == clean


def test_parse_digest_falls_back_to_a_headline_slug_for_the_event_key() -> None:
    """An empty event key becomes a slug of the headline."""
    raw = {"headline": "Lab ships model", "score": 60, "event_key": ""}
    assert parse_digest(raw, KEYS).event_key == "lab-ships-model"


@pytest.mark.parametrize("raw", [None, {"score": 50}, {"headline": "H", "score": None},
                                 {"headline": "H", "score": True}])
def test_parse_digest_rejects_unusable_replies(raw: object) -> None:
    """No headline, or no numeric score, is an unusable reply."""
    with pytest.raises(ValueError):
        parse_digest(raw, KEYS)


def test_slugify_limits_length() -> None:
    """Slugs are ASCII, dash-joined and capped without a trailing dash."""
    assert slugify("A--B  c!") == "a-b-c"
    assert slugify("x" * 50 + " y", limit=51) == "x" * 50
