"""One engine for every OpenAI-compatible chat-completions API.

OpenRouter, OpenAI, Ollama, LM Studio and any custom address that speaks the same protocol are
the same code with a different base URL and key. The answer streams as Server-Sent Events:
`data: {...}` lines carrying `choices[0].delta.content`, ended by `data: [DONE]`.

The API key is passed in by the registry, sent only in the Authorization header, and never
logged or put in an error message.
"""

import ipaddress
import json
import logging
import time
from collections.abc import Iterator
from urllib.parse import urlsplit

import httpx

from spyglass_service.radar.assist.engines.base import MAX_OUTPUT_TOKENS, StreamEvent, http_error_message
from spyglass_service.radar.assist.engines.cache_blocks import mark_last_message, system_blocks
from spyglass_service.radar.assist.engines.sse import iter_sse
from spyglass_service.radar.egress import SecretDestinationError, api_client, engine_secret_name
from spyglass_service.radar.usage_parse import Tokens, openai_tokens

logger = logging.getLogger(__name__)

# connect/write/pool are short; read is the longest gap allowed between two chunks, which covers
# a model that thinks for a while before its first token.
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
# A local server either answers at once or is not running; do not make the page wait on it.
_PROBE_TIMEOUT = httpx.Timeout(0.8)

# Local-server probes are remembered briefly: one page load asks "available?" and "which models?"
# for each local engine, and a closed port should not be tried twice in a row.
_PROBE_TTL_S = 5.0
_probe_cache: dict[str, tuple[float, list[dict] | None]] = {}


def clear_probe_cache() -> None:
    """Forget remembered local-server probes (used after configuration changes and in tests)."""
    _probe_cache.clear()


def is_loopback_host(host: str) -> bool:
    """True for localhost and for loopback IP addresses (127.0.0.0/8, ::1)."""
    name = host.strip("[]").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def key_may_travel(base_url: str) -> bool:
    """Whether an API key may be sent to `base_url`: always over https, over http only to loopback."""
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return bool(parts.hostname)
    return parts.scheme == "http" and bool(parts.hostname) and is_loopback_host(parts.hostname)


PRESETS: dict[str, dict] = {
    "openrouter": {"label": "OpenRouter", "kind": "api", "base_url": "https://openrouter.ai/api/v1",
                   "key_required": True},
    "openai": {"label": "OpenAI API", "kind": "api", "base_url": "https://api.openai.com/v1",
               "key_required": True},
    # Google's OpenAI-compatible endpoint for the Gemini API (the address is fixed in code).
    "gemini": {"label": "Google Gemini API", "kind": "api",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "key_required": True},
    "ollama": {"label": "Ollama (this computer)", "kind": "local",
               "base_url": "http://127.0.0.1:11434/v1", "key_required": False},
    "lmstudio": {"label": "LM Studio (this computer)", "kind": "local",
                 "base_url": "http://127.0.0.1:1234/v1", "key_required": False},
}


class OpenAICompatEngine:
    """Streams answers from any server that implements /chat/completions with SSE."""

    def __init__(
        self,
        *,
        id: str,  # noqa: A002 -- the engine's public identifier
        label: str,
        kind: str,
        base_url: str,
        api_key: str | None = None,
        key_required: bool = True,
        models: list[dict] | None = None,
        live_models: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Set up the engine; `models` is the offered list, `live_models` asks /models instead."""
        self.id = id
        self.label = label
        self.kind = kind
        self._base = base_url.rstrip("/")
        self._key = api_key or None
        self._key_required = key_required
        self._models = list(models or [])
        self._live = live_models
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        """Request headers; the Authorization header only when a key is set."""
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        # A key is never put on a plain-http connection to another machine, whatever stored it.
        if self._key and key_may_travel(self._base):
            headers["Authorization"] = f"Bearer {self._key}"
        if self.id == "openrouter":
            headers["X-Title"] = "Spyglass"
        return headers

    def _client(self, timeout: float | httpx.Timeout) -> httpx.Client:
        """A client that refuses to send this engine's key anywhere but its own service.

        When a key is attached, every request is checked against the key's binding (the preset
        services' fixed hosts, or this server's own configured host). Without a key, any request
        that would still carry a credential is refused. Redirects are never followed.
        """
        sends_key = bool(self._key and key_may_travel(self._base))
        return api_client(engine_secret_name(self.id) if sends_key else None, timeout=timeout,
                          transport=self._transport, bound_host=urlsplit(self._base).hostname)

    def _fetch_models(self) -> list[dict] | None:
        """Ask the server which models it has; None when it cannot be reached.

        Local servers are probed at most once every few seconds.
        """
        cached = _probe_cache.get(self._base)
        if self.kind != "api" and cached and time.monotonic() - cached[0] < _PROBE_TTL_S:
            return cached[1]
        result = self._probe()
        if self.kind != "api":
            _probe_cache[self._base] = (time.monotonic(), result)
        return result

    def _probe(self) -> list[dict] | None:
        """One GET /models request."""
        try:
            with self._client(_PROBE_TIMEOUT) as client:
                response = client.get(f"{self._base}/models", headers=self._headers())
            response.raise_for_status()
            rows = response.json().get("data", [])
        except SecretDestinationError:
            logger.warning("%s: the key was refused for this address", self.id)
            return None
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        return [{"id": str(r["id"]), "label": str(r["id"])} for r in rows
                if isinstance(r, dict) and r.get("id")]

    def models(self) -> list[dict]:
        """The offered models: live from the server for local engines, else the configured list."""
        if self._live:
            live = self._fetch_models()
            if live is not None:
                return live
        return list(self._models)

    def available(self) -> tuple[bool, str | None]:
        """Usable when a key exists (if one is needed) and, for local servers, the port answers."""
        if self._key_required and not self._key:
            return False, "No API key set"
        if self.kind == "local":
            if self._fetch_models() is None:
                return False, f"{self.label} is not running (nothing answers at {self._base})"
        return True, None

    def _messages(self, system: str, messages: list[dict], model: str) -> list[dict]:
        """The chat messages. Anthropic models behind OpenRouter only cache where the request marks
        it (OpenRouter's `cache_control` blocks); every other provider caches a repeated beginning by
        itself, so the plain text is sent."""
        if self.id == "openrouter" and model.startswith("anthropic/"):
            return [{"role": "system", "content": system_blocks(system)}, *mark_last_message(messages)]
        return [{"role": "system", "content": system}, *messages]

    def stream(
        self,
        *,
        system: str,
        messages: list[dict],
        model: str,
        session: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream one answer. `session` is unused: the full history is sent every turn."""
        payload = {
            "model": model,
            "stream": True,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": self._messages(system, messages, model),
        }
        if self.kind == "api":
            # Hosted services send the token figures in a last chunk only when asked. A local or
            # custom server may reject a field it does not know, so it is not asked.
            payload["stream_options"] = {"include_usage": True}
        got_text = False
        tokens: Tokens | None = None
        try:
            with self._client(_TIMEOUT) as client:
                with client.stream("POST", f"{self._base}/chat/completions", json=payload,
                                   headers=self._headers()) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        yield StreamEvent.error(http_error_message(self.label, response.status_code, body))
                        return
                    for _, data in iter_sse(response.iter_lines()):
                        if data.strip() == "[DONE]":
                            break
                        text, failure = _parse_chunk(data)
                        tokens = _chunk_tokens(data) or tokens
                        if failure:
                            yield StreamEvent.error(f"{self.label}: {failure}")
                            return
                        if text:
                            got_text = True
                            yield StreamEvent.delta(text)
        except httpx.TimeoutException:
            yield StreamEvent.error(f"{self.label} stopped answering (timed out).")
            return
        except httpx.HTTPError as exc:
            logger.warning("%s request failed: %s", self.id, type(exc).__name__)
            yield StreamEvent.error(f"Could not reach {self.label}.")
            return
        except SecretDestinationError:
            logger.warning("%s: the key was refused for this address", self.id)
            yield StreamEvent.error(f"{self.label}: the key may not be sent to this address.")
            return
        if not got_text:
            yield StreamEvent.error(f"{self.label} returned an empty answer.")
            return
        if tokens is not None:
            yield StreamEvent.usage(tokens)
        yield StreamEvent.done()


def _chunk_tokens(data: str) -> Tokens | None:
    """The token figures in one `data:` payload (the last chunk carries them), or None."""
    try:
        chunk = json.loads(data)
    except ValueError:
        return None
    return openai_tokens(chunk.get("usage")) if isinstance(chunk, dict) else None


def _parse_chunk(data: str) -> tuple[str, str | None]:
    """Pull (text, error) out of one `data:` payload; unparseable chunks are skipped as empty."""
    try:
        chunk = json.loads(data)
    except ValueError:
        return "", None
    if not isinstance(chunk, dict):
        return "", None
    err = chunk.get("error")
    if err:
        message = err.get("message") if isinstance(err, dict) else str(err)
        return "", " ".join(str(message or "the provider reported an error").split())[:200]
    choices = chunk.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return "", None
    delta = choices[0].get("delta") or {}
    content = delta.get("content") if isinstance(delta, dict) else None
    return (content if isinstance(content, str) else ""), None
