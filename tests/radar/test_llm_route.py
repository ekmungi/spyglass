"""Tests for routing one bulk call through the provider chain with the right model per provider."""

from types import SimpleNamespace

import pytest

from spyglass_service.radar.llm_chain import Cooldowns, provider_order
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.llm_route import routed_chat_json

SCHEMA = {"name": "x", "schema": {"type": "object"}}
MESSAGES = [{"role": "user", "content": "hi"}]


def settings(**overrides):
    base = {"radar_llm_provider": "openrouter", "radar_llm_fallback": "claude_code,gemini",
            "radar_triage_model": "or-triage", "radar_digest_model": "or-digest",
            "radar_writer_model": "or-writer", "radar_claude_triage_model": "haiku",
            "radar_claude_digest_model": "sonnet", "radar_claude_writer_model": "haiku"}
    return SimpleNamespace(**{**base, **overrides})


class Calls:
    """Records which provider was asked with which model; answers or fails per provider."""

    def __init__(self, fail=()):
        self.fail, self.log = set(fail), []

    def openrouter(self, s, model, messages, schema):
        self.log.append(("openrouter", model))
        if "openrouter" in self.fail:
            raise LlmUnavailable("out of credit")
        return {"from": "openrouter"}

    def gemini(self, s, model, messages, schema):
        self.log.append(("gemini", model))
        if "gemini" in self.fail:
            raise LlmUnavailable("no key")
        return {"from": "gemini"}

    def claude(self, messages, schema, *, model, settings, runner=None):
        self.log.append(("claude_code", model))
        if "claude_code" in self.fail:
            raise LlmUnavailable("not signed in")
        return {"from": "claude_code", "runner": runner}


def route(calls, role="digest", **kw):
    return routed_chat_json(settings(), role, MESSAGES, SCHEMA, openrouter_call=calls.openrouter,
                            gemini_call=calls.gemini, claude_call=calls.claude,
                            cooldowns=Cooldowns(), **kw)


def test_the_primary_answers_with_its_own_role_model():
    calls = Calls()
    assert route(calls) == {"from": "openrouter"}
    assert calls.log == [("openrouter", "or-digest")]


def test_the_model_follows_the_provider_that_actually_answers():
    calls = Calls(fail={"openrouter"})
    assert route(calls)["from"] == "claude_code"
    assert calls.log == [("openrouter", "or-digest"), ("claude_code", "sonnet")]
    calls = Calls(fail={"openrouter", "claude_code"})
    assert route(calls)["from"] == "gemini"
    assert calls.log[-1] == ("gemini", "gemini-3.8-flash")


def test_an_explicit_model_applies_to_the_primary_only():
    calls = Calls(fail={"openrouter"})
    route(calls, model="judge-model")
    assert calls.log[0] == ("openrouter", "judge-model")
    assert calls.log[1] == ("claude_code", "sonnet")


def test_the_runner_reaches_the_claude_call():
    calls = Calls(fail={"openrouter"})
    sentinel = object()
    assert route(calls, runner=sentinel)["runner"] is sentinel


def test_everything_down_names_every_provider():
    calls = Calls(fail={"openrouter", "claude_code", "gemini"})
    with pytest.raises(LlmUnavailable) as caught:
        route(calls)
    text = str(caught.value)
    assert "openrouter" in text and "claude_code" in text and "gemini" in text


def test_an_unknown_primary_falls_back_to_openrouter():
    assert provider_order(settings(radar_llm_provider="mystery", radar_llm_fallback="")) == [
        "openrouter"]
