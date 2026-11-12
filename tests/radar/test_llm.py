"""Tests for the provider seam: provider and model choice per role, availability, error mapping."""

import httpx
import pytest

from spyglass_service.config import Settings
from spyglass_service.openrouter import OpenRouterError
from spyglass_service.radar import llm, llm_chain
from spyglass_service.radar.brief.llm import make_llm
from spyglass_service.radar.llm import LlmUnavailable, available, chat_json_for, model_for, provider
from spyglass_service.radar.llm_claude import RunResult

MESSAGES = [{"role": "user", "content": "hi"}]
SCHEMA = {"name": "t", "schema": {"type": "object", "required": ["ok"]}}


def make(tmp_path, monkeypatch, **extra) -> Settings:
    """Settings that ignore `.env`; the OpenRouter key comes from the environment as in the app."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return Settings(_env_file=None, data_dir=tmp_path, claude_command="claude", **extra)


def test_provider_and_model_per_role(tmp_path, monkeypatch) -> None:
    """Each role maps to its own model under each provider."""
    cfg = make(tmp_path, monkeypatch, radar_triage_model="t", radar_digest_model="d",
               radar_writer_model="w")
    assert provider(cfg) == "openrouter"
    assert [model_for(cfg, r) for r in ("triage", "digest", "writer")] == ["t", "d", "w"]
    cfg = make(tmp_path, monkeypatch, radar_llm_provider="claude_code",
               radar_claude_triage_model="sonnet", radar_claude_digest_model="haiku",
               radar_claude_writer_model="opus")
    assert provider(cfg) == "claude_code"
    assert [model_for(cfg, r) for r in ("triage", "digest", "writer")] == ["sonnet", "haiku", "opus"]
    with pytest.raises(ValueError):
        model_for(cfg, "other")


def test_openrouter_route_uses_key_and_role_model(tmp_path, monkeypatch) -> None:
    """The OpenRouter route forwards the role's model and the key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    cfg = Settings(_env_file=None, data_dir=tmp_path, radar_writer_model="w-model")
    seen = {}

    def fake(messages, schema, *, model, api_key):
        """Capture the call."""
        seen.update(model=model, key=api_key)
        return {"ok": 1}

    monkeypatch.setattr(llm, "chat_json", fake)
    assert chat_json_for(cfg, "writer", MESSAGES, SCHEMA) == {"ok": 1}
    assert seen == {"model": "w-model", "key": "k"}
    assert chat_json_for(cfg, "writer", MESSAGES, SCHEMA, model="other") == {"ok": 1}
    assert seen["model"] == "other"


@pytest.mark.parametrize(("status", "text"), [
    ("402", "out of credit"), ("429", "rate limiting"), ("401", "rejected the key"),
    ("500", "could not be used")])
def test_openrouter_failures_become_unavailable(tmp_path, monkeypatch, status, text) -> None:
    """OpenRouter failures carry a short human message."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    cfg = Settings(_env_file=None, data_dir=tmp_path)

    def fail(*_a, **_k):
        """Raise the client's failure for this status."""
        raise OpenRouterError(f"OpenRouter request failed (last status {status})")

    monkeypatch.setattr(llm, "chat_json", fail)
    with pytest.raises(LlmUnavailable, match=text):
        chat_json_for(cfg, "triage", MESSAGES, SCHEMA)


def test_openrouter_network_error_and_missing_key(tmp_path, monkeypatch) -> None:
    """A network error and a missing key are both LlmUnavailable."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    cfg = Settings(_env_file=None, data_dir=tmp_path)

    def boom(*_a, **_k):
        """Raise a transport error."""
        raise httpx.ConnectError("down")

    monkeypatch.setattr(llm, "chat_json", boom)
    with pytest.raises(LlmUnavailable, match="could not be reached"):
        chat_json_for(cfg, "digest", MESSAGES, SCHEMA)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(LlmUnavailable, match="No OpenRouter key"):
        chat_json_for(Settings(_env_file=None, data_dir=tmp_path), "digest", MESSAGES, SCHEMA)


def test_claude_route_uses_role_model_and_runner(tmp_path, monkeypatch) -> None:
    """With the Claude provider the role's alias reaches the command, and the reply is parsed."""
    cfg = make(tmp_path, monkeypatch, radar_llm_provider="claude_code",
               radar_claude_triage_model="sonnet", radar_claude_writer_model="haiku")
    commands = []

    def runner(command, prompt, cwd, timeout_s) -> RunResult:
        """Record the model flag and answer with a structured object."""
        commands.append(command[command.index("--model") + 1])
        return RunResult(0, '{"type":"result","is_error":false,"structured_output":{"ok":true}}', "")

    assert chat_json_for(cfg, "triage", MESSAGES, SCHEMA, runner=runner) == {"ok": True}
    assert chat_json_for(cfg, "writer", MESSAGES, SCHEMA, runner=runner) == {"ok": True}
    assert chat_json_for(cfg, "writer", MESSAGES, SCHEMA, model="opus", runner=runner) == {"ok": True}
    assert commands == ["sonnet", "haiku", "opus"]


def test_available_and_make_llm(tmp_path, monkeypatch) -> None:
    """available() explains a missing key or command; make_llm needs no OpenRouter key for Claude."""
    cfg = make(tmp_path, monkeypatch)
    assert available(cfg) == (False, "No OpenRouter key is set.")
    assert make_llm(cfg) is None
    cfg = make(tmp_path, monkeypatch, radar_llm_provider="claude_code")
    monkeypatch.setattr(llm_chain, "_find_claude", lambda _s: "claude")
    assert available(cfg) == (True, None)
    assert callable(make_llm(cfg))
    monkeypatch.setattr(llm_chain, "_find_claude", lambda _s: None)
    ok, reason = available(cfg)
    assert not ok and "not found" in reason
    assert make_llm(cfg) is None


def test_judge_and_default_llm_follow_the_provider(tmp_path, monkeypatch) -> None:
    """Under the Claude provider the judge carries the Claude models and default_llm routes there."""
    from spyglass_service.radar import assess

    cfg = make(tmp_path, monkeypatch, radar_llm_provider="claude_code",
               radar_claude_triage_model="sonnet", radar_claude_digest_model="haiku")
    seen = []

    def fake(settings, role, messages, schema, *, model=None, runner=None):
        """Capture the role and model the judge's call function chose."""
        seen.append((role, model))
        return {"ok": 1}

    monkeypatch.setattr(assess, "chat_json_for", fake)
    call = assess.default_llm(cfg)
    assert call([], SCHEMA, "sonnet") == {"ok": 1} and call([], SCHEMA, "haiku") == {"ok": 1}
    assert seen == [("triage", "sonnet"), ("digest", "haiku")]

def test_the_judge_passes_its_role_even_when_both_passes_share_a_model(tmp_path, monkeypatch) -> None:
    """With one model for both passes the role comes from the pass, not from guessing the name."""
    from spyglass_service.radar import assess

    cfg = make(tmp_path, monkeypatch, radar_claude_triage_model="haiku",
               radar_claude_digest_model="haiku", radar_llm_provider="claude_code")
    seen = []
    monkeypatch.setattr(assess, "chat_json_for",
                        lambda settings, role, messages, schema, *, model=None: seen.append(role) or {})
    call = assess.default_llm(cfg)
    assess._call(call, [], SCHEMA, "haiku", "digest")
    assess._call(call, [], SCHEMA, "haiku", "triage")
    assert seen == ["digest", "triage"]


def test_primary_gemini_and_a_ready_fallback_make_the_provider_available(tmp_path, monkeypatch) -> None:
    """available() defers to the chain: a fallback that is ready counts when the primary is not."""
    cfg = make(tmp_path, monkeypatch, radar_llm_fallback="claude_code")
    monkeypatch.setattr("spyglass_service.radar.llm_chain._find_claude", lambda _s: "claude")
    assert available(cfg) == (True, None)  # no OpenRouter key, but the claude command is found
    monkeypatch.setattr(llm_chain, "_find_claude", lambda _s: None)
    assert available(cfg) == (False, "No OpenRouter key is set.")
    gem = make(tmp_path, monkeypatch, radar_llm_provider="gemini")
    assert provider(gem) == "gemini" and model_for(gem, "triage").startswith("gemini")
    monkeypatch.setattr("spyglass_service.radar.llm_chain._stored_key", lambda _n: None)
    assert available(gem) == (False, "No Gemini key is set.")


@pytest.mark.parametrize("name", ["openrouter", "claude_code", "gemini", "antigravity"])
def test_chat_json_for_goes_through_the_router_for_every_provider(
        tmp_path, monkeypatch, name) -> None:
    """Every provider name reaches `routed_chat_json` (not a direct OpenRouter call), with the
    privacy-prepared messages, the explicit model and the OpenRouter call as the fallback hook."""
    cfg = make(tmp_path, monkeypatch, radar_llm_provider=name)
    seen = {}

    def fake_router(settings, role, messages, schema, *, model=None, runner=None,
                    openrouter_call, **_extra):
        """Capture what the seam hands to the router."""
        seen.update(provider=provider(settings), role=role, model=model, messages=messages,
                    hook=openrouter_call)
        return {"ok": name}

    monkeypatch.setattr(llm, "routed_chat_json", fake_router)
    assert chat_json_for(cfg, "digest", MESSAGES, SCHEMA, model="m-x") == {"ok": name}
    assert (seen["provider"], seen["role"], seen["model"]) == (name, "digest", "m-x")
    assert seen["hook"] is llm._openrouter_json
    assert any("hi" in str(m.get("content")) for m in seen["messages"])  # prepared, not dropped


def test_available_follows_the_whole_provider_order(tmp_path, monkeypatch) -> None:
    """available() is the chain's answer: a ready antigravity fallback counts."""
    monkeypatch.setattr(llm_chain, "_agy_ready", lambda _s: (True, None))
    cfg = make(tmp_path, monkeypatch, radar_llm_fallback="antigravity")
    assert available(cfg) == (True, None)
    monkeypatch.setattr(llm_chain, "_agy_ready", lambda _s: (False, "Antigravity is not installed."))
    assert available(cfg) == (False, "No OpenRouter key is set.")
