"""The Anthropic Messages API, streamed.

Request: POST /v1/messages with `stream: true`. The response is Server-Sent Events; the answer
text arrives in `content_block_delta` events whose delta has `type: text_delta`, and the stream
ends with `message_stop`. An `error` event can arrive mid-stream.

The API key goes only in the `x-api-key` header and is never logged or shown.
"""

import json
import logging
from collections.abc import Iterator

import httpx

from spyglass_service.radar.assist.engines.base import MAX_OUTPUT_TOKENS, StreamEvent, http_error_message
from spyglass_service.radar.assist.engines.cache_blocks import mark_last_message, system_blocks
from spyglass_service.radar.assist.engines.sse import iter_sse
from spyglass_service.radar.egress import api_client, assert_secret_destination
from spyglass_service.radar.usage_parse import anthropic_tokens

logger = logging.getLogger(__name__)

_URL = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# Names as the Anthropic API spells them (the OpenRouter ids use dots instead of the last dash).
DEFAULT_MODELS: list[dict] = [
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
]


class AnthropicEngine:
    """Streams answers from the Anthropic Messages API with the reader's own API key."""

    id = "anthropic"
    label = "Claude API"
    kind = "api"

    def __init__(
        self,
        *,
        api_key: str | None,
        models: list[dict] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`models` overrides the built-in list; `transport` lets tests avoid the network."""
        self._key = api_key or None
        self._models = list(models) if models else list(DEFAULT_MODELS)
        self._transport = transport

    def models(self) -> list[dict]:
        """The offered Claude models."""
        return list(self._models)

    def available(self) -> tuple[bool, str | None]:
        """Usable once an API key is set."""
        return (True, None) if self._key else (False, "No API key set")

    def stream(
        self,
        *,
        system: str,
        messages: list[dict],
        model: str,
        session: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream one answer. `session` is unused: the full history is sent every turn."""
        headers = {
            "x-api-key": self._key or "",
            "anthropic-version": _VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        # Two cache breakpoints: the system prompt (the article, the same on every turn) and the last
        # message (the conversation so far). The default five-minute lifetime costs the least.
        payload = {"model": model, "max_tokens": MAX_OUTPUT_TOKENS, "stream": True,
                   "system": system_blocks(system), "messages": mark_last_message(messages)}
        got_text = False
        start_usage: object = None
        last_usage: object = None
        try:
            # The key may only go to the Anthropic API; the client re-checks every request.
            assert_secret_destination("anthropic_api_key", _URL)
            with api_client("anthropic_api_key", timeout=_TIMEOUT,
                            transport=self._transport) as client:
                with client.stream("POST", _URL, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        yield StreamEvent.error(http_error_message(self.label, response.status_code, body))
                        return
                    for event, data in iter_sse(response.iter_lines()):
                        try:
                            body = json.loads(data)
                        except ValueError:
                            continue
                        if not isinstance(body, dict):
                            continue
                        if event == "error" or body.get("type") == "error":
                            err = body.get("error") if isinstance(body.get("error"), dict) else {}
                            message = " ".join(str(err.get("message") or "the API reported an error").split())
                            yield StreamEvent.error(f"{self.label}: {message[:200]}")
                            return
                        if body.get("type") == "content_block_delta":
                            delta = body.get("delta") or {}
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                got_text = True
                                yield StreamEvent.delta(str(delta["text"]))
                        elif body.get("type") == "message_start":
                            start_usage = (body.get("message") or {}).get("usage")
                        elif body.get("type") == "message_delta":
                            last_usage = body.get("usage")
                        elif body.get("type") == "message_stop":
                            break
        except httpx.TimeoutException:
            yield StreamEvent.error(f"{self.label} stopped answering (timed out).")
            return
        except httpx.HTTPError as exc:
            logger.warning("anthropic request failed: %s", type(exc).__name__)
            yield StreamEvent.error(f"Could not reach {self.label}.")
            return
        if not got_text:
            yield StreamEvent.error(f"{self.label} returned an empty answer.")
            return
        tokens = anthropic_tokens(start_usage, last_usage)
        if tokens is not None:
            yield StreamEvent.usage(tokens)
        yield StreamEvent.done()
