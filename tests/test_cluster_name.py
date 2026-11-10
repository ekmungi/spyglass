"""Tests for the cluster-naming LLM contract.

Mirrors the enrich_prompt split: the prompt/parse are pure and unit-tested here; the default
namer is a thin binder over openrouter.chat_json, exercised with a stubbed call.
"""

from types import SimpleNamespace

from spyglass_service import cluster_name
from spyglass_service.cluster_name import (
    build_name_messages,
    default_namer,
    parse_cluster_name,
)


def test_build_name_messages_lists_titles_and_asks_for_json() -> None:
    """The user message enumerates the cluster's titles; the system message pins JSON output."""
    messages = build_name_messages(["Surgical robot arm", "Autonomous drone swarm"])
    system, user = messages[0]["content"], messages[1]["content"]
    assert "JSON" in system
    assert "Surgical robot arm" in user and "Autonomous drone swarm" in user


def test_parse_cluster_name_trims_whitespace() -> None:
    """A model name with stray whitespace is trimmed to the bare label."""
    assert parse_cluster_name({"name": "  Robotics  "}) == "Robotics"


def test_parse_cluster_name_missing_is_empty_string() -> None:
    """A malformed response (no name) yields an empty string, not a crash."""
    assert parse_cluster_name({}) == ""


def test_default_namer_passes_titles_and_returns_parsed_name(monkeypatch) -> None:
    """default_namer feeds the titles through the prompt and returns the parsed model name."""
    captured: dict = {}

    def fake_chat_json(messages, schema, *, model, api_key, **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        return {"name": "Robotics"}

    monkeypatch.setattr(cluster_name, "chat_json", fake_chat_json)
    namer = default_namer(SimpleNamespace(enrich_model="deepseek", openrouter_api_key="key"))
    assert namer(["Surgical robot arm"]) == "Robotics"
    assert captured["model"] == "deepseek"
    assert "Surgical robot arm" in captured["messages"][1]["content"]
