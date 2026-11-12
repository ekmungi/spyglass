"""One structured-JSON call to any OpenAI-compatible chat endpoint, and the Gemini preset of it.

Used for bulk judging when "gemini" is a provider name in the fallback order. Failures to reach
the model surface as `LlmUnavailable` with a short message the reader can act on; a reply that is
not a usable JSON object surfaces as ValueError (which never makes the caller switch provider).

The key is sent only in the Authorization header, only over https and only to a host the caller
allows, and is never logged or put in an error message.
"""

import json
import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from spyglass_service.radar import egress, usage
from spyglass_service.radar.llm_claude import extract_json, schema_body, validate
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.usage_parse import openai_tokens

logger = logging.getLogger(__name__)

# Google's OpenAI-compatible endpoint for the Gemini API (verified against Google's own
# documentation). The assistant engine uses the same address.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_HOSTS = frozenset({"generativelanguage.googleapis.com"})
_RETRY_STATUS = (500, 502, 503, 504)
_ATTEMPTS = 3


def _error_text(response: httpx.Response) -> str:
    """The provider's own short error message, for the log only (never shown with a key)."""
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        text = err.get("message") if isinstance(err, dict) else str(err or "")
    except ValueError:
        text = response.text
    return " ".join(str(text).split())[:200]


def _check_destination(base_url: str, allowed_hosts: frozenset[str] | set[str] | None,
                       label: str) -> None:
    """Refuse to send a key anywhere but https and an allowed host."""
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        raise LlmUnavailable(f"{label} must be reached over https.")
    if allowed_hosts is not None and parts.hostname.lower() not in allowed_hosts:
        raise LlmUnavailable(f"{label} has an address this app does not send keys to.")


def _plain_json_messages(messages: list[dict], body: dict) -> list[dict]:
    """The messages with the schema spelled out in the first system message (json_object mode)."""
    instruction = ("Reply with one JSON object that validates against this JSON Schema and "
                   "nothing else: no commentary and no code fence.\n" + json.dumps(body))
    if messages and messages[0].get("role") == "system":
        first = {**messages[0], "content": f"{messages[0].get('content', '')}\n\n{instruction}"}
        return [first, *messages[1:]]
    return [{"role": "system", "content": instruction}, *messages]


def _status_error(label: str, status: int, response: httpx.Response) -> LlmUnavailable:
    """Map an HTTP failure to the reader-facing message."""
    logger.warning("%s answered %s: %s", label, status, _error_text(response))
    if status in (401, 403):
        return LlmUnavailable(f"{label} rejected the key.")
    if status == 402:
        return LlmUnavailable(f"The {label} account is out of credit.")
    if status == 429:
        return LlmUnavailable(f"{label} is rate limiting requests or the usage limit is reached;"
                              " try again later.")
    return LlmUnavailable(f"{label} could not be used (status {status}).")


def _post(client: httpx.Client, url: str, headers: dict, payload: dict, label: str,
          sleep: Callable[[float], None]) -> httpx.Response:
    """POST with a short retry on server errors; returns the final response."""
    response = client.post(url, json=payload, headers=headers)
    for attempt in range(1, _ATTEMPTS):
        if response.status_code not in _RETRY_STATUS:
            break
        logger.warning("%s answered %s (attempt %d/%d)", label, response.status_code, attempt,
                       _ATTEMPTS)
        sleep(0.5 * attempt)
        response = client.post(url, json=payload, headers=headers)
    return response


def _content(response: httpx.Response) -> str:
    """The text of the first choice, or ValueError when the answer has none."""
    try:
        text = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("the reply has no message text") from exc
    if not isinstance(text, str) or not text.strip():
        raise ValueError("the reply has no message text")
    return text


def chat_json(
    messages: list[dict],
    schema: dict,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    label: str = "The model",
    allowed_hosts: frozenset[str] | set[str] | None = None,
    secret_name: str | None = "gemini_api_key",
    transport: httpx.BaseTransport | None = None,
    timeout: float = 90.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """One structured-JSON chat completion from an OpenAI-compatible endpoint.

    messages/schema: as for `openrouter.chat_json` (`schema` is `{"name", "schema"}` or bare).
    base_url: the endpoint root, without `/chat/completions`. allowed_hosts: when given, the only
    hosts the key may be sent to. secret_name: the `radar.egress.SECRET_HOSTS` entry (or
    `engine:<id>` name) the key belongs to; the client refuses to send it anywhere else. Raises LlmUnavailable for a missing or refused key, no credit,
    rate limiting, a server that keeps failing or cannot be reached; ValueError when the reply is
    not a JSON object with the schema's required keys. A 400 about the schema is retried once in
    plain JSON mode with the schema written into the prompt.
    """
    if not api_key:
        raise LlmUnavailable(f"No {label} key is set.")
    _check_destination(base_url, allowed_hosts, label)
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = schema_body(schema)
    payload = {"model": model, "messages": messages, "response_format": {
        "type": "json_schema",
        "json_schema": {"name": str(schema.get("name") or "reply"), "schema": body}}}
    started = time.monotonic()
    try:
        with egress.api_client(secret_name, timeout=timeout, transport=transport) as client:
            response = _post(client, url, headers, payload, label, sleep)
            if response.status_code == 400:
                logger.info("%s refused the schema (%s); retrying in plain JSON mode", label,
                            _error_text(response))
                plain = {"model": model, "messages": _plain_json_messages(messages, body),
                         "response_format": {"type": "json_object"}}
                response = _post(client, url, headers, plain, label, sleep)
                if response.status_code == 400:
                    raise ValueError(f"{label} rejected the request: {_error_text(response)}")
    except egress.SecretDestinationError as exc:
        # The client's own check refused the destination before anything was sent.
        raise LlmUnavailable(f"{label} has an address this app does not send keys to.") from exc
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"{label} could not be reached ({type(exc).__name__}).") from exc
    if response.status_code != 200:
        raise _status_error(label, response.status_code, response)
    usage.note_call(provider="gemini", model=model, tokens=_response_tokens(response),
                    duration_ms=int((time.monotonic() - started) * 1000))
    return validate(extract_json(_content(response)), schema)


def _response_tokens(response: httpx.Response):
    """The token figures in a chat-completions reply, or None when it has none."""
    try:
        return openai_tokens(response.json().get("usage"))
    except (ValueError, AttributeError):
        return None


def gemini_chat_json(settings, model: str, messages: list[dict], schema: dict, *,
                     transport: httpx.BaseTransport | None = None) -> dict:
    """`chat_json` against the Gemini API, with the key from the settings or the keyring."""
    from spyglass_service.radar import llm_chain

    key = getattr(settings, "gemini_api_key", None) or llm_chain._stored_key("gemini")  # noqa: SLF001
    return chat_json(messages, schema, base_url=GEMINI_BASE_URL, api_key=key, model=model,
                     label="Gemini", allowed_hosts=GEMINI_HOSTS, secret_name="gemini_api_key",
                     transport=transport)
