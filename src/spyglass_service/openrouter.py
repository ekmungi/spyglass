"""Minimal OpenRouter (OpenAI-compatible) client.

`chat_json` -- structured output, synchronous, one parsed object back. Used by the enrichment
pipeline until a planned Claude morning run replaces it. The streaming client behind the
in-reader chat pane went with the pane.

The API key is read by the caller from settings and passed in; it is never logged here. A
transport is injectable so tests run without network (httpx.MockTransport).
"""

import json
import logging
import time

import httpx

from spyglass_service.radar import usage
from spyglass_service.radar.egress import api_client, assert_secret_destination
from spyglass_service.radar.privacy import scrub_messages
from spyglass_service.radar.usage_parse import openai_tokens

logger = logging.getLogger(__name__)

_URL = "https://openrouter.ai/api/v1/chat/completions"
# Retry on rate-limit + transient server errors; exponential-ish backoff between tries.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    """Raised when a structured chat completion cannot be obtained (no key / retries exhausted)."""


def _settings() -> object:
    """The settings in effect (environment, .env and the dashboard overlay), for the scrub.

    Fails closed: when they cannot be loaded, nothing is sent.
    """
    from spyglass_service.config import Settings, apply_overlay

    try:
        return apply_overlay(Settings())
    except Exception as exc:  # noqa: BLE001 -- any failure means the request cannot be checked
        raise OpenRouterError("Settings could not be loaded to check the request.") from exc


def chat_json(
    messages: list[dict],
    schema: dict,
    *,
    model: str,
    api_key: str,
    transport: httpx.BaseTransport | None = None,
    max_retries: int = 3,
    timeout: float = 90.0,
    settings: object | None = None,
) -> dict:
    """Post a structured-output chat completion and return the parsed JSON object.

    messages: OpenAI-style messages, system/interest-statement first (stable-prefix-first).
    schema: a json_schema dict ({"name", "schema"}) for response_format.
    model/api_key: the model id and OpenRouter key (never logged).
    settings: the settings whose secrets and personal details are removed from the messages
    before sending; the settings in effect are loaded when omitted (a backstop for callers that
    do not go through `radar.llm.chat_json_for`).
    Retries _RETRY_STATUS responses up to max_retries with linear backoff. Raises
    OpenRouterError on a missing key, when the settings cannot be loaded for the check, or once
    retries are exhausted.
    """
    if not api_key:
        raise OpenRouterError("OpenRouter API key is not configured")
    payload = {
        "model": model,
        "messages": scrub_messages(messages, settings if settings is not None else _settings()),
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    # The key may only go to OpenRouter; the client re-checks every request it sends.
    assert_secret_destination("openrouter_api_key", _URL)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_status = None
    with api_client("openrouter_api_key", timeout=timeout, transport=transport) as client:
        for attempt in range(max_retries):
            started = time.monotonic()
            response = client.post(_URL, json=payload, headers=headers)
            if response.status_code == 200:
                body = response.json()
                usage.note_call(provider="openrouter", model=model,
                                tokens=openai_tokens(body.get("usage")),
                                duration_ms=int((time.monotonic() - started) * 1000))
                content = body["choices"][0]["message"]["content"]
                return json.loads(content)
            last_status = response.status_code
            if response.status_code not in _RETRY_STATUS:
                break
            logger.warning("OpenRouter %s (attempt %d/%d)", response.status_code, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                time.sleep(0.2 * (attempt + 1))
    raise OpenRouterError(f"OpenRouter request failed (last status {last_status})")
