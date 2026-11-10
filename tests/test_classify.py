"""Tests for the LLM category re-classification contract.

Constrains the LLM to the user's chosen categories (enum + null) -- the same closed-vocabulary
guarantee as new-item enrichment, applied to the backlog. Prompt/parse are pure; the default
classifier is a thin binder over openrouter.chat_json.
"""

from types import SimpleNamespace

from spyglass_service import classify
from spyglass_service.classify import (
    build_classify_messages,
    classify_schema,
    default_classifier,
    parse_category,
)


def test_classify_schema_is_enum_over_categories_plus_null() -> None:
    """`category` is constrained to exactly the user's set plus null (Unsorted)."""
    schema = classify_schema(["Healthcare AI", "Robotics"])
    assert schema["schema"]["properties"]["category"]["enum"] == ["Healthcare AI", "Robotics", None]


def test_build_classify_messages_lists_categories_and_content() -> None:
    """The system message lists the allowed categories; the user message carries the article."""
    messages = build_classify_messages(
        "Surgical Robot Study", "A robot for surgery.", ["robot"], ["Healthcare AI", "Robotics"]
    )
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Healthcare AI" in system and "Robotics" in system
    assert "Surgical Robot Study" in user


def test_parse_category_keeps_in_set_value() -> None:
    """A category within the allowed set is kept."""
    assert parse_category({"category": "Robotics"}, {"Healthcare AI", "Robotics"}) == "Robotics"


def test_parse_category_maps_stray_to_none() -> None:
    """A value outside the set becomes None (Unsorted) -- the post-validation backstop."""
    assert parse_category({"category": "Cooking"}, {"Healthcare AI", "Robotics"}) is None


def test_parse_category_null_or_missing_is_none() -> None:
    """Explicit null or a missing field both mean Unsorted."""
    assert parse_category({"category": None}, {"Healthcare AI"}) is None
    assert parse_category({}, {"Healthcare AI"}) is None


def test_default_classifier_returns_parsed_category(monkeypatch) -> None:
    """default_classifier feeds the article through the prompt and returns the parsed category."""
    captured: dict = {}

    def fake_chat_json(messages, schema, *, model, api_key, **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        return {"category": "Robotics"}

    monkeypatch.setattr(classify, "chat_json", fake_chat_json)
    clf = default_classifier(
        SimpleNamespace(enrich_model="deepseek", openrouter_api_key="k"),
        ["Healthcare AI", "Robotics"],
    )
    assert clf("Robot arm", "A robot.", ["robot"]) == "Robotics"
    assert captured["model"] == "deepseek"
    assert "Robot arm" in captured["messages"][1]["content"]
