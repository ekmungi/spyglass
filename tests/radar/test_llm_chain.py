"""Tests for the provider fallback chain: order, switching rules, cooldown memory and status."""

import threading
from types import SimpleNamespace

import pytest

from spyglass_service.radar import llm_chain
from spyglass_service.radar.llm_chain import (
    COOLDOWN_SECONDS,
    Cooldowns,
    call_with_fallback,
    model_for_provider,
    provider_order,
    status,
)
from spyglass_service.radar.llm_errors import LlmUnavailable


def make_settings(**overrides):
    """A settings stand-in with the fields the chain reads."""
    base = {
        "radar_llm_provider": "openrouter", "radar_llm_fallback": "",
        "radar_triage_model": "or-triage", "radar_digest_model": "or-digest",
        "radar_writer_model": "or-writer",
        "radar_claude_triage_model": "haiku", "radar_claude_digest_model": "sonnet",
        "radar_claude_writer_model": "haiku",
        "openrouter_api_key": "k", "gemini_api_key": None, "claude_command": "",
    }
    return SimpleNamespace(**{**base, **overrides})


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cooldowns(clock: Clock) -> Cooldowns:
    return Cooldowns(clock=clock)


class Recorder:
    """A call_one stand-in: records the providers asked and answers from a script."""

    def __init__(self, script: dict) -> None:
        self.script, self.calls = script, []

    def __call__(self, name: str) -> dict:
        self.calls.append(name)
        outcome = self.script[name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run(settings, recorder, cooldowns, order=None):
    return call_with_fallback(settings, "triage", [], {}, call_one=recorder, order=order,
                              cooldowns=cooldowns)


# ---- order ---------------------------------------------------------------------------------

def test_order_is_the_primary_then_the_fallbacks_without_repeats():
    settings = make_settings(radar_llm_provider="claude_code",
                             radar_llm_fallback="openrouter, gemini ,claude_code,openrouter")
    assert provider_order(settings) == ["claude_code", "openrouter", "gemini"]


def test_order_ignores_unknown_names_and_blank_entries():
    settings = make_settings(radar_llm_fallback=" ,nonsense,gemini,")
    assert provider_order(settings) == ["openrouter", "gemini"]


def test_order_with_no_fallback_is_just_the_primary():
    assert provider_order(make_settings()) == ["openrouter"]


# ---- switching rules -----------------------------------------------------------------------

def test_primary_answers_and_no_fallback_is_tried(cooldowns):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": {"a": 1}, "gemini": {"a": 2}})
    assert run(settings, rec, cooldowns) == {"a": 1}
    assert rec.calls == ["openrouter"]


def test_unavailable_primary_falls_through_to_the_next_provider(cooldowns):
    settings = make_settings(radar_llm_fallback="claude_code,gemini")
    rec = Recorder({"openrouter": LlmUnavailable("The OpenRouter account is out of credit."),
                    "claude_code": LlmUnavailable("Claude Code is not signed in."),
                    "gemini": {"ok": True}})
    assert run(settings, rec, cooldowns) == {"ok": True}
    assert rec.calls == ["openrouter", "claude_code", "gemini"]


def test_malformed_reply_does_not_switch_provider(cooldowns):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": ValueError("not json"), "gemini": {"ok": True}})
    with pytest.raises(ValueError):
        run(settings, rec, cooldowns)
    assert rec.calls == ["openrouter"]
    assert cooldowns.until("openrouter") is None


def test_a_provider_is_never_tried_twice_in_one_call(cooldowns):
    settings = make_settings(radar_llm_fallback="openrouter,openrouter")
    rec = Recorder({"openrouter": LlmUnavailable("down")})
    with pytest.raises(LlmUnavailable):
        run(settings, rec, cooldowns)
    assert rec.calls == ["openrouter"]


def test_all_failing_raises_one_error_naming_every_provider_and_reason(cooldowns):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": LlmUnavailable("The OpenRouter account is out of credit."),
                    "gemini": LlmUnavailable("Gemini rejected the key.")})
    with pytest.raises(LlmUnavailable) as caught:
        run(settings, rec, cooldowns)
    message = str(caught.value)
    assert "openrouter" in message and "out of credit" in message
    assert "gemini" in message and "rejected the key" in message


def test_explicit_order_overrides_the_settings(cooldowns):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"gemini": {"g": 1}, "openrouter": {"o": 1}})
    assert run(settings, rec, cooldowns, order=["gemini", "openrouter"]) == {"g": 1}
    assert rec.calls == ["gemini"]


def test_other_errors_are_not_swallowed(cooldowns):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": KeyError("bug")})
    with pytest.raises(KeyError):
        run(settings, rec, cooldowns)
    assert rec.calls == ["openrouter"]


# ---- cooldown memory -----------------------------------------------------------------------

def test_a_dead_provider_is_not_retried_during_the_cooldown(cooldowns, clock):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": LlmUnavailable("out of credit"), "gemini": {"ok": True}})
    for _ in range(600):
        assert run(settings, rec, cooldowns) == {"ok": True}
    assert rec.calls.count("openrouter") == 1
    assert rec.calls.count("gemini") == 600


def test_the_cooldown_ends_after_ten_minutes(cooldowns, clock):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": LlmUnavailable("out of credit"), "gemini": {"ok": True}})
    run(settings, rec, cooldowns)
    clock.now += COOLDOWN_SECONDS - 1
    run(settings, rec, cooldowns)
    assert rec.calls.count("openrouter") == 1
    clock.now += 2
    run(settings, rec, cooldowns)
    assert rec.calls.count("openrouter") == 2


def test_with_every_provider_cooling_down_no_call_is_made_and_the_reason_is_kept(
        cooldowns, clock):
    settings = make_settings(radar_llm_fallback="gemini")
    rec = Recorder({"openrouter": LlmUnavailable("The OpenRouter account is out of credit."),
                    "gemini": LlmUnavailable("Gemini rejected the key.")})
    with pytest.raises(LlmUnavailable):
        run(settings, rec, cooldowns)
    with pytest.raises(LlmUnavailable) as caught:
        run(settings, rec, cooldowns)
    assert rec.calls == ["openrouter", "gemini"]
    assert "out of credit" in str(caught.value) and "rejected the key" in str(caught.value)


def test_a_single_provider_is_retried_every_time_so_a_fixed_account_works_at_once(
        cooldowns, clock):
    settings = make_settings()
    rec = Recorder({"openrouter": LlmUnavailable("The OpenRouter account is out of credit.")})
    for _ in range(3):
        with pytest.raises(LlmUnavailable):
            run(settings, rec, cooldowns)
    assert rec.calls == ["openrouter"] * 3
    assert cooldowns.until("openrouter") is None


def test_reset_clears_one_provider_or_all(cooldowns):
    cooldowns.mark("openrouter", "x")
    cooldowns.mark("gemini", "y")
    cooldowns.reset("openrouter")
    assert cooldowns.until("openrouter") is None and cooldowns.until("gemini") is not None
    cooldowns.reset()
    assert cooldowns.until("gemini") is None


def test_cooldowns_are_safe_under_threads(cooldowns):
    def worker() -> None:
        for i in range(200):
            cooldowns.mark(f"p{i % 3}", "r")
            cooldowns.until(f"p{i % 3}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(cooldowns.until(f"p{i}") is not None for i in range(3))


# ---- models follow the provider ------------------------------------------------------------

def test_model_follows_the_provider_that_answers():
    settings = make_settings()
    assert model_for_provider(settings, "openrouter", "triage") == "or-triage"
    assert model_for_provider(settings, "claude_code", "digest") == "sonnet"
    assert model_for_provider(settings, "gemini", "writer").startswith("gemini-")


def test_unknown_role_or_provider_is_a_value_error():
    with pytest.raises(ValueError):
        model_for_provider(make_settings(), "openrouter", "poet")
    with pytest.raises(ValueError):
        model_for_provider(make_settings(), "mystery", "triage")


# ---- status --------------------------------------------------------------------------------

def test_status_lists_every_provider_with_availability_and_cooldown(
        cooldowns, clock, monkeypatch):
    monkeypatch.setattr(llm_chain, "_find_claude", lambda settings: None)
    monkeypatch.setattr(llm_chain, "_stored_key", lambda name: None)
    settings = make_settings(radar_llm_fallback="claude_code", gemini_api_key="g")
    cooldowns.mark("openrouter", "The OpenRouter account is out of credit.")
    rows = {r["name"]: r for r in status(settings, cooldowns=cooldowns)}
    assert set(rows) == {"openrouter", "claude_code", "gemini", "antigravity"}
    assert rows["openrouter"]["available"] is False
    assert rows["openrouter"]["reason"] == "The OpenRouter account is out of credit."
    assert rows["openrouter"]["cooling_down_until"] is not None
    assert rows["claude_code"]["available"] is False
    assert "claude command" in rows["claude_code"]["reason"]
    assert rows["gemini"]["available"] is True and rows["gemini"]["position"] is None
    assert rows["openrouter"]["position"] == 1 and rows["claude_code"]["position"] == 2


def test_any_available_is_true_when_a_fallback_can_run(monkeypatch):
    monkeypatch.setattr(llm_chain, "_find_claude", lambda settings: "claude")
    monkeypatch.setattr(llm_chain, "_stored_key", lambda name: None)
    settings = make_settings(openrouter_api_key=None, radar_llm_fallback="claude_code")
    assert llm_chain.any_available(settings) == (True, None)


def test_any_available_names_the_primary_reason_when_none_can_run(monkeypatch):
    monkeypatch.setattr(llm_chain, "_find_claude", lambda settings: None)
    monkeypatch.setattr(llm_chain, "_stored_key", lambda name: None)
    settings = make_settings(openrouter_api_key=None)
    ok, reason = llm_chain.any_available(settings)
    assert ok is False and "OpenRouter" in reason
