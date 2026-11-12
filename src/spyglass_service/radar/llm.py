"""The single seam for the radar's bulk model calls: triage, digest and the small writing jobs.

`chat_json_for` hands the call to `llm_route`, which tries the provider named in
`settings.radar_llm_provider` first and then the ones in `radar_llm_fallback`, each with its own
model for the job's role, and returns one parsed JSON object. Every failure to reach a model surfaces as `LlmUnavailable` with a short message the
reader can act on; an answer that is not valid JSON surfaces as ValueError, which the judging code
treats as an unusable reply.

Before any provider sees the messages, `privacy.prepare_bulk_messages` removes secrets, the
reader's e-mail address and personal file paths, fences the user messages (items, articles,
search results) as material, and puts the standing instruction about that material first.
"""

import logging
import re
from typing import Literal

import httpx

from spyglass_service.openrouter import OpenRouterError, chat_json
from spyglass_service.radar import usage
from spyglass_service.radar.llm_chain import any_available, model_for_provider, provider_order
from spyglass_service.radar.llm_claude import Runner
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.llm_route import routed_chat_json
from spyglass_service.radar.privacy import prepare_bulk_messages

__all__ = ["LlmUnavailable", "Role", "available", "chat_json_for", "model_for", "provider"]

logger = logging.getLogger(__name__)

Role = Literal["triage", "digest", "writer"]
_STATUS = re.compile(r"last status (\d+)")


def provider(settings) -> str:
    """The primary provider: the first name in the configured order (openrouter by default)."""
    return provider_order(settings)[0]


def model_for(settings, role: str) -> str:
    """The model id for `role` under the primary provider."""
    return model_for_provider(settings, provider(settings), role)


def available(settings) -> tuple[bool, str | None]:
    """Whether some provider in the configured order can be tried, and if not, why.

    The primary provider's missing key or command is the reason given when none can be used.
    Being signed in, or having usage left, is only known by trying, and is reported by
    `chat_json_for` when it fails.
    """
    return any_available(settings)


def _openrouter_json(settings, model: str, messages: list[dict], schema: dict) -> dict:
    """One OpenRouter structured-output call, with failures mapped to LlmUnavailable."""
    key = getattr(settings, "openrouter_api_key", None)
    if not key:
        raise LlmUnavailable("No OpenRouter key is set.")
    try:
        return chat_json(messages, schema, model=model, api_key=key)
    except OpenRouterError as exc:
        status = _STATUS.search(str(exc))
        code = status.group(1) if status else ""
        if code == "402":
            raise LlmUnavailable("The OpenRouter account is out of credit.") from exc
        if code == "429":
            raise LlmUnavailable("OpenRouter is rate limiting requests; try again later.") from exc
        if code in ("401", "403"):
            raise LlmUnavailable("OpenRouter rejected the key.") from exc
        raise LlmUnavailable(f"OpenRouter could not be used: {exc}") from exc
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"OpenRouter could not be reached: {exc}") from exc


def chat_json_for(
    settings,
    role: Role,
    messages: list[dict],
    schema: dict,
    *,
    model: str | None = None,
    runner: Runner | None = None,
    purpose: str | None = None,
) -> dict:
    """One structured-JSON model call for `role` through the configured provider.

    messages/schema: as for `openrouter.chat_json`. model: overrides the role's configured model
    (the judge passes the model it was built with). runner: replaces the Claude process launch
    (tests). Raises LlmUnavailable when the provider cannot be used right now and ValueError when
    the model answered without a usable JSON object. purpose: what the call is for in the usage
    table (see `radar.usage.PURPOSES`); the role decides when it is omitted.
    """
    # The seam: secrets and personal details out, web text fenced, before any provider sees it.
    messages = prepare_bulk_messages(messages, settings)
    with usage.call_scope(settings, purpose or usage.default_purpose(role)):
        return routed_chat_json(settings, role, messages, schema, model=model, runner=runner,
                                openrouter_call=_openrouter_json)
