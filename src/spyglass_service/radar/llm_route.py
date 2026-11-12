"""Route one bulk model call through the provider chain, using each provider's own model.

`radar.llm.chat_json_for` hands its arguments here. The first provider in the configured order is
tried first; when it cannot be used the next one is, and the model changes with the provider (the
OpenRouter ids for OpenRouter, Claude aliases for Claude Code, a Gemini id for Gemini, an
Antigravity slug or Antigravity's own default for Antigravity). An explicit `model` (the judge
passes the one it was built with) belongs to the first provider only.
"""

from collections.abc import Callable

from spyglass_service.radar.llm_agy import agy_chat_json
from spyglass_service.radar.llm_chain import (
    Cooldowns,
    call_with_fallback,
    model_for_provider,
    provider_order,
)
from spyglass_service.radar.llm_claude import claude_chat_json
from spyglass_service.radar.llm_openai_compat import gemini_chat_json

__all__ = ["routed_chat_json"]


def routed_chat_json(
    settings,
    role: str,
    messages: list[dict],
    schema: dict,
    *,
    model: str | None = None,
    runner=None,
    openrouter_call: Callable[..., dict],
    gemini_call: Callable[..., dict] = gemini_chat_json,
    claude_call: Callable[..., dict] = claude_chat_json,
    agy_call: Callable[..., dict] = agy_chat_json,
    cooldowns: Cooldowns | None = None,
) -> dict:
    """One structured-JSON call for `role`, trying each configured provider in order.

    openrouter_call(settings, model, messages, schema) makes the OpenRouter call (it lives in
    `radar.llm`, which owns its error mapping). gemini_call, claude_call and agy_call default to
    the real ones and are replaced in tests. Raises LlmUnavailable naming every provider when none
    could be used, and ValueError when the provider that answered gave an unusable reply.
    """
    order = provider_order(settings)

    def call_one(name: str) -> dict:
        chosen = model if (model and name == order[0]) else model_for_provider(settings, name, role)
        if name == "claude_code":
            return claude_call(messages, schema, model=chosen, settings=settings, runner=runner)
        if name == "gemini":
            return gemini_call(settings, chosen, messages, schema)
        if name == "antigravity":
            return agy_call(messages, schema, model=chosen, settings=settings)
        return openrouter_call(settings, chosen, messages, schema)

    return call_with_fallback(settings, role, messages, schema, call_one=call_one, order=order,
                              cooldowns=cooldowns)
