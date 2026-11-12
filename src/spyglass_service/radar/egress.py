"""Where data may leave this computer, and which secret may be sent where.

Two rules are enforced here, in one place:

1. A secret goes only to its own service. `SECRET_HOSTS` binds every secret setting to the exact
   host names it may be sent to, and `assert_secret_destination` raises before a request is made
   to any other host, over plain http, or to an address carrying user info. Keys the reader
   stores for one assistant server are bound to that server's own configured host. The
   model-API client built by `api_client` runs that check on every request it sends and never
   follows a redirect, so a key cannot be carried somewhere else by a server's answer.
2. A search query built from model output stays a search query. `safe_search_query` refuses
   empty, over-long, multi-line or address-carrying text before it is sent to a search service.

The table of every outside service Spyglass contacts, with what each one receives, lives in
`egress_destinations.py` and is re-exported here; a regression test checks that every host used
in the code appears in it.
"""

import ipaddress
import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx

from spyglass_service.radar.egress_destinations import (
    DESTINATIONS,
    LINK_ONLY_HOSTS,
    Destination,
    destinations_for,
    documented_hosts,
)

__all__ = [
    "DESTINATIONS", "ENGINE_SECRETS", "LINK_ONLY_HOSTS", "SECRET_HOSTS", "Destination",
    "SecretDestinationError", "UnsafeQuery", "api_client", "assert_secret_destination",
    "destinations_for", "documented_hosts", "engine_secret_name", "safe_search_query",
]

# Secret setting -> the only hosts it may be sent to. Exact names: no subdomains, no wildcards.
SECRET_HOSTS: Mapping[str, frozenset[str]] = MappingProxyType({
    "openrouter_api_key": frozenset({"openrouter.ai"}),
    "anthropic_api_key": frozenset({"api.anthropic.com"}),
    "openai_api_key": frozenset({"api.openai.com"}),
    "gemini_api_key": frozenset({"generativelanguage.googleapis.com"}),
    "slack_bot_token": frozenset({"slack.com", "files.slack.com"}),
    "slack_app_token": frozenset({"slack.com"}),
    "raindrop_token": frozenset({"api.raindrop.io"}),
    "gmail_app_password": frozenset({"imap.gmail.com"}),
    "jina_api_key": frozenset({"r.jina.ai"}),
})

# Assistant engines whose key is one of the settings secrets above (from the environment or the
# keyring entry with the same engine id): they share that secret's binding.
ENGINE_SECRETS: Mapping[str, str] = MappingProxyType({
    "openrouter": "openrouter_api_key", "anthropic": "anthropic_api_key",
    "openai": "openai_api_key", "gemini": "gemini_api_key"})

# Secret names for keys stored per assistant server: bound to that server's configured host.
ENGINE_PREFIX = "engine:"

# Schemes a secret may travel over: https for web APIs, imaps for the mail server.
_SECURE_SCHEMES = frozenset({"https", "imaps"})
# Request headers that carry a credential.
_CREDENTIAL_HEADERS = ("authorization", "x-api-key", "proxy-authorization", "cookie")

# Longest search query sent to a search service.
MAX_QUERY_CHARS = 200
# Anything that looks like a web address or a bare host with a path: a query is search text only.
_ADDRESS = re.compile(
    r"([a-z][a-z0-9+.-]*://)|(\bwww\.)|(\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}/)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SecretDestinationError(RuntimeError):
    """A secret was about to be sent to a host it is not bound to; nothing was sent."""


class UnsafeQuery(ValueError):
    """A search query was refused: empty, too long, not plain text, or carrying an address."""


def engine_secret_name(engine_id: str) -> str:
    """The secret name an assistant engine's key is checked under.

    The preset API engines share the binding of the settings secret they use; every other engine
    (local servers, custom servers) gets `engine:<id>`, bound to its own configured host.
    """
    return ENGINE_SECRETS.get(engine_id, f"{ENGINE_PREFIX}{engine_id}")


def _is_loopback(host: str) -> bool:
    """True for localhost and loopback IP addresses."""
    name = host.strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _allowed_hosts(secret_name: str, bound_host: str | None) -> frozenset[str]:
    """The hosts `secret_name` may go to; raises for an unknown name or a missing bound host."""
    if secret_name in SECRET_HOSTS:
        # A bound host never widens a settings secret's binding.
        return SECRET_HOSTS[secret_name]
    if secret_name.startswith(ENGINE_PREFIX):
        if not bound_host:
            raise SecretDestinationError("An assistant server key has no configured host.")
        return frozenset({bound_host.strip("[]").lower()})
    raise SecretDestinationError("That secret has no permitted destination.")


def assert_secret_destination(secret_name: str, url: str, *, bound_host: str | None = None) -> None:
    """Raise `SecretDestinationError` unless `secret_name` may be sent to `url`.

    Args:
        secret_name: A key of `SECRET_HOSTS`, or `engine:<id>` for a key stored for one assistant
            server (see `engine_secret_name`).
        url: The full address the request is about to go to.
        bound_host: For `engine:<id>` names only, the host of that server's configured address.

    The host must match exactly; the scheme must be https (imaps for mail), except that a key
    for a server on this computer may use plain http; user info in the address is refused.
    """
    allowed = _allowed_hosts(secret_name, bound_host)
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    scheme = parts.scheme.lower()
    secure = scheme in _SECURE_SCHEMES or (
        scheme == "http" and secret_name.startswith(ENGINE_PREFIX) and _is_loopback(host))
    if not host or host not in allowed or not secure or parts.username or parts.password:
        raise SecretDestinationError(
            f"Refused to send {secret_name} to {host or 'an address without a host'}.")


def _carries_credential(request: httpx.Request) -> bool:
    """True when the request has a header that carries a credential."""
    return any(name in request.headers for name in _CREDENTIAL_HEADERS)


def api_client(secret_name: str | None, *, timeout: float | httpx.Timeout = 60.0,
               transport: httpx.BaseTransport | None = None,
               bound_host: str | None = None) -> httpx.Client:
    """The one way to build an HTTP client for a model or service API.

    With `secret_name`, every request it sends is checked with `assert_secret_destination`
    before it leaves. With None (a server that takes no key), any request that still carries a
    credential header is refused. Redirects are never followed, so an answer cannot move the
    request, and its key, somewhere else.
    """

    def check(request: httpx.Request) -> None:
        """Request hook: refuse any request whose credential would reach the wrong host."""
        if secret_name is None:
            if _carries_credential(request):
                raise SecretDestinationError("Refused to send a credential with no bound host.")
            return
        assert_secret_destination(secret_name, str(request.url), bound_host=bound_host)

    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=False,
                        event_hooks={"request": [check], "response": []})


def safe_search_query(query: str) -> str:
    """Return `query` when it is safe to send as search text; raise `UnsafeQuery` otherwise.

    Safe means: text, one line with no control characters, 1 to 200 characters after trimming,
    and no web address or host-with-path inside (search text cannot smuggle a link to a service
    that later fetches it).
    """
    if not isinstance(query, str):
        raise UnsafeQuery("A search query must be text.")
    if _CONTROL.search(query):
        raise UnsafeQuery("A search query must be one line of plain text.")
    text = query.strip()
    if not text or len(text) > MAX_QUERY_CHARS:
        raise UnsafeQuery(f"A search query must be 1 to {MAX_QUERY_CHARS} characters.")
    if _ADDRESS.search(text):
        raise UnsafeQuery("A search query must not contain a web address.")
    return text
