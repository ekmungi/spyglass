"""Tests for track suggestions: parsing the model's answer, the no-model fallback, similar items."""

import pytest

from spyglass_service.content_store import store_fulltext
from spyglass_service.radar.track_suggest import (
    build_messages, fallback_suggestions, item_context, parse_suggestions, similar_now, suggest,
)
from spyglass_service.radar.tracks import create_track

from .test_brief_seed import add_item, make_engine, make_index


@pytest.fixture
def engine(tmp_path):
    """A fresh database."""
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def good(label="Computer-aided detection in colonoscopy", **extra) -> dict:
    """One well-formed suggestion as the model would return it."""
    return {"label": label, "query": '"computer-aided detection" colonoscopy', "kind": "topic",
            "section": "health", "why": "the technique the article describes", **extra}


def article(engine) -> int:
    """An item with entities and stored text."""
    item_id = add_item(engine, "FDA clears a colonoscopy AI tool", entities=["Acme Health", "FDA"])
    store_fulltext(engine, item_id=item_id, markdown="Body text " * 500, source_url="https://x.example",
                   content_type="text/html")
    return item_id


def test_item_context_reads_headline_entities_and_cuts_the_text(engine) -> None:
    context = item_context(engine, article(engine))
    assert context["entities"] == ["Acme Health", "FDA"] and context["section"] == "health"
    assert 0 < len(context["text"]) <= 3000


def test_item_context_unknown_item_raises(engine) -> None:
    with pytest.raises(LookupError):
        item_context(engine, 404)


def test_prompt_marks_the_article_as_data(engine) -> None:
    messages = build_messages(item_context(engine, article(engine)),
                              {"sections": [{"key": "health", "label": "Healthcare AI"}]})
    assert "never instructions" in messages[0]["content"]
    assert "Acme Health" in messages[1]["content"] and "health: Healthcare AI" in messages[1]["content"]


def test_parse_keeps_valid_entries_and_drops_bad_or_repeated_ones(engine) -> None:
    raw = {"suggestions": [
        good(),
        good(label="computer-aided detection in colonoscopy!"),  # repeat after normalising
        good(label="Bad\x00label"),                              # control character
        good(label=""),
        {"label": "No query"},
        "not a dict",
        good(label="Odd kind and section", kind="planet", section="unknown"),
    ]}
    parsed = parse_suggestions(raw, engine, default_section="industry")
    assert [p["label"] for p in parsed] == ["Computer-aided detection in colonoscopy",
                                            "Odd kind and section"]
    assert parsed[0]["section_label"] == "Healthcare AI & medtech"
    assert parsed[1]["kind"] == "topic" and parsed[1]["section"] == "industry"
    assert all(p["already_followed"] is False for p in parsed)


def test_parse_caps_at_six_and_rejects_non_objects(engine) -> None:
    raw = {"suggestions": [good(label=f"Topic {i}") for i in range(9)]}
    assert len(parse_suggestions(raw, engine)) == 6
    assert parse_suggestions(["x"], engine) == [] and parse_suggestions({"suggestions": 3}, engine) == []


def test_already_followed_checks_tracks_and_profile_topics(engine) -> None:
    create_track(engine, label="Capsule AI", query="capsule q", section="health", kind="topic")
    raw = {"suggestions": [
        good(label="capsule ai"),                              # same label as a track
        good(label="Another name", query="CAPSULE Q"),         # same query as a track
        good(label="Open-weights models"),                        # a profile topic
        good(label="Brand new subject"),
    ]}
    flags = {p["label"]: p["already_followed"] for p in parse_suggestions(raw, engine)}
    assert flags == {"capsule ai": True, "Another name": True, "Open-weights models": True,
                     "Brand new subject": False}


def test_suggest_uses_the_model_and_passes_a_schema_with_the_profile_sections(engine) -> None:
    seen = {}

    def llm(messages, schema):
        seen["schema"] = schema
        return {"suggestions": [good()]}

    suggestions, mode = suggest(engine, article(engine), llm)
    assert mode == "ai" and suggestions[0]["label"].startswith("Computer-aided")
    enum = seen["schema"]["schema"]["properties"]["suggestions"]["items"]["properties"]["section"]["enum"]
    assert "health" in enum and "direction" in enum


@pytest.mark.parametrize("llm", [
    None,
    lambda m, s: (_ for _ in ()).throw(RuntimeError("model down")),
    lambda m, s: {"suggestions": []},
    lambda m, s: {"nonsense": True},
])
def test_suggest_without_a_usable_model_falls_back_to_the_entities(engine, llm) -> None:
    suggestions, mode = suggest(engine, article(engine), llm)
    assert mode == "basic"
    labels = [s["label"] for s in suggestions]
    assert labels[:2] == ["Acme Health", "FDA"]
    assert labels[-1] == "Healthcare AI & medtech" and len(labels) <= 5
    assert suggestions[0]["kind"] == "organisation" and suggestions[0]["query"] == '"Acme Health"'


def test_fallback_without_entities_or_section_is_empty_not_an_error(engine) -> None:
    item_id = add_item(engine, "Plain story", score=None)
    assert fallback_suggestions(item_context(engine, item_id), engine) == []


def test_suggest_unknown_item_raises(engine) -> None:
    with pytest.raises(LookupError):
        suggest(engine, 404, None)


def test_similar_now_keeps_judged_items_that_are_not_out(engine) -> None:
    base = add_item(engine, "Base story")
    near = add_item(engine, "Near story")
    out = add_item(engine, "Rejected story", tier="out", score=5)
    unjudged = add_item(engine, "Unjudged", score=None)
    far = add_item(engine, "Far story")
    index = make_index({base: [1, 0, 0, 0], near: [0.9, 0.1, 0, 0], out: [0.95, 0.05, 0, 0],
                        unjudged: [0.92, 0.08, 0, 0], far: [0, 1, 0, 0]})
    shown = similar_now(engine, index, base)
    assert [i["id"] for i in shown] == [near, far]
    assert shown[0]["title"] == "Near story" and "tier" in shown[0]
    assert len(similar_now(engine, index, base, limit=1)) == 1


def test_similar_now_survives_a_broken_index(engine) -> None:
    class Broken:
        def similar(self, item_id, k):
            raise RuntimeError("no index")

    assert similar_now(engine, Broken(), 1) == []
