"""Guard for outbound requests: only public http(s) addresses may be fetched.

Links come from feeds, searches and the reader's own captures, so any of them could point
at this computer or a private network. Every fetch the radar layer starts checks its target
here first, and `guard_client` makes that check structural: a client wrapped by it re-checks every
request it sends, including each redirect hop, so no code path has to remember to do it. The same
wrapper makes page fetching read-only and anonymous: GET and HEAD only, no cookies, no
credential headers and one fixed, generic User-Agent (`page_client` builds such a client).

A host name could give a public answer to the check and a private answer a moment later, when the
connection is made (DNS rebinding). `checked_addresses` hands the approved addresses to the
fetching paths so they connect to exactly those (see netpin.py); what remains is described there.
"""

import ipaddress
import socket
import threading
import time
from collections.abc import Callable
from enum import Enum
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpcore
import httpx

from spyglass_service.feed_http import BROWSER_USER_AGENT

# The one User-Agent every page fetch sends: a generic browser string with the product name,
# fixed in code, so it never carries a user name, machine name, address or path.
PAGE_USER_AGENT = BROWSER_USER_AGENT
# The only methods a page-fetch client may send.
READ_METHODS = frozenset({"GET", "HEAD"})
# Headers that could identify the reader or carry a credential; never sent with a page fetch.
_PERSONAL_HEADERS = ("cookie", "authorization", "proxy-authorization")

# Resolves a host name to its addresses; replaced in tests so no lookup leaves the machine.
Resolver = Callable[[str], list[str]]

# Host-name endings that always mean "not on the public internet".
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".intranet")


# Ranges the standard library does not class as private but that are not public either:
# carrier-grade NAT, and the NAT64 prefix that can map onto private IPv4 addresses.
_EXTRA_PRIVATE_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("64:ff9b::/96"),
)


def is_private_address(text: str) -> bool:
    """True when `text` is an IP literal in a private, loopback, link-local or reserved range."""
    try:
        address = ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return False
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified):
        return True
    return any(address in network for network in _EXTRA_PRIVATE_NETWORKS)


def resolve(host: str) -> list[str]:
    """All addresses a host name resolves to. Raises OSError when it does not resolve."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _is_address_literal(host: str) -> bool:
    """True when `host` is an IP address written out, as opposed to a name."""
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def is_internal_host(host: str) -> bool:
    """True when a host is `localhost`, ends in an internal suffix or is a private address literal.

    This decides from the text alone, with no lookup, so a request interceptor can use it for
    every sub-resource a page asks for. A public-looking name that resolves privately is not
    caught here; `is_public_url` resolves names and catches it.
    """
    host = host.lower().strip("[]")
    return host == "localhost" or host.endswith(_INTERNAL_SUFFIXES) or is_private_address(host)


class Reach(Enum):
    """The outcome of an address check."""

    PUBLIC = "public"  # http(s), a public host, resolving only to public addresses
    NOT_PUBLIC = "not_public"  # not http(s), user info, an internal name or a private address
    UNRESOLVED = "unresolved"  # the name could not be looked up (often a passing DNS hiccup)


# Seconds to wait before the one retry of a failed lookup.
LOOKUP_RETRY_DELAY = 0.3
# Seconds a successful lookup is reused, so parallel fetches of one host do not each ask DNS.
LOOKUP_CACHE_SECONDS = 60.0
# Cache size at which expired entries are swept out.
_CACHE_SWEEP_AT = 1024

# Replaced in tests: the pause before a retry, and the clock the cache expires by.
_sleep = time.sleep
_now = time.monotonic

# host -> (expires at, addresses, the resolver that produced them). An entry is reused only for
# the same resolver object, so replacing `resolve` (as tests do) never reuses an older answer.
_lookup_cache: dict[str, tuple[float, tuple[str, ...], Callable]] = {}
_cache_lock = threading.Lock()
# One lock per host, so parallel checks of the same host wait for a single lookup.
_host_locks: dict[str, threading.Lock] = {}


def clear_lookup_cache() -> None:
    """Forget every cached lookup (tests, and after network changes)."""
    with _cache_lock:
        _lookup_cache.clear()


def _cached(host: str, fn: Callable) -> list[str] | None:
    """A still-valid cached answer for `host` from `fn`, or None."""
    with _cache_lock:
        entry = _lookup_cache.get(host)
    if entry and entry[0] > _now() and entry[2] is fn:
        return list(entry[1])
    return None


def _store(host: str, addresses: list[str], fn: Callable) -> None:
    """Cache a successful answer, sweeping expired entries when the cache has grown."""
    now = _now()
    with _cache_lock:
        if len(_lookup_cache) >= _CACHE_SWEEP_AT:
            for key in [k for k, v in _lookup_cache.items() if v[0] <= now]:
                del _lookup_cache[key]
        _lookup_cache[host] = (now + LOOKUP_CACHE_SECONDS, tuple(addresses), fn)


def _resolve_twice(host: str, fn: Callable) -> list[str] | None:
    """Look `host` up, retrying once after a short pause; None when both attempts fail."""
    for attempt in range(2):
        try:
            return list(fn(host))
        except OSError:
            if attempt == 0:
                _sleep(LOOKUP_RETRY_DELAY)
    return None


def _lookup(host: str, resolver: Resolver | None) -> list[str] | None:
    """The addresses of `host`, or None when it could not be resolved.

    A custom resolver (a pinned answer) is asked every time. The module's own `resolve` is
    cached for `LOOKUP_CACHE_SECONDS`; parallel callers for one host share a single lookup.
    """
    if resolver is not None:
        return _resolve_twice(host, resolver)
    fn = resolve  # looked up through the module so a test can replace `netguard.resolve`
    hit = _cached(host, fn)
    if hit is not None:
        return hit
    with _cache_lock:
        host_lock = _host_locks.setdefault(host, threading.Lock())
    with host_lock:
        hit = _cached(host, fn)  # another thread may have looked it up meanwhile
        if hit is not None:
            return hit
        addresses = _resolve_twice(host, fn)
        if addresses:
            _store(host, addresses, fn)
        return addresses


def check_url(url: str, resolver: Resolver | None = None) -> Reach:
    """Decide whether `url` may be fetched: `Reach.PUBLIC`, `NOT_PUBLIC` or `UNRESOLVED`.

    PUBLIC needs http(s), no user info, a public host and only public addresses for it. A name
    whose lookup fails twice is UNRESOLVED: callers must still refuse to send the request, but
    should report it as a passing failure ("could not be reached"), not as a refused address.
    The check is made just before the request, so a name that changes its answer between the
    check and the connection could still slip through; redirects are re-checked hop by hop.
    """
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in ("http", "https") or not host:
        return Reach.NOT_PUBLIC
    if parts.username or parts.password:
        return Reach.NOT_PUBLIC
    if is_internal_host(host):
        return Reach.NOT_PUBLIC
    if _is_address_literal(host):
        return Reach.PUBLIC  # a public address literal; the private ranges were refused above
    addresses = _lookup(host, resolver)
    if not addresses:
        return Reach.UNRESOLVED
    return Reach.NOT_PUBLIC if any(is_private_address(a) for a in addresses) else Reach.PUBLIC


def is_public_url(url: str, resolver: Resolver | None = None) -> bool:
    """True when `check_url` says PUBLIC: anything else (including a failed lookup) is refused."""
    return check_url(url, resolver) is Reach.PUBLIC


# The reason given for a host name that could not be looked up (a passing failure).
UNREACHABLE = "The site could not be reached; try again."


class UnpinnableHost(httpcore.ConnectError):
    """A connection was not made: the host has no public address that passed the check."""


def checked_addresses(host: str) -> list[str]:
    """The public addresses `host` was checked against, to connect to exactly those.

    Uses the same cached lookup as `check_url`, so a connection made right after a check goes to
    the addresses that check approved. Raises `UnpinnableHost` for an internal or private host,
    a name with a private answer, or a name that could not be looked up.
    """
    name = (host or "").lower().strip("[]")
    if not name or is_internal_host(name):
        raise UnpinnableHost("This address cannot be fetched.")
    if _is_address_literal(name):
        return [name]
    addresses = _lookup(name, None)
    if not addresses:
        raise UnpinnableHost(UNREACHABLE)
    if any(is_private_address(a) for a in addresses):
        raise UnpinnableHost("This address cannot be fetched.")
    return addresses


# Redirects a guarded client follows before giving up. Longer chains fail rather than run on.
MAX_REDIRECTS = 8


class BlockedAddress(httpx.RequestError):
    """A request was refused because its address is not on the public internet."""


class UnresolvedAddress(httpx.ConnectError):
    """A request was not sent because its host name could not be looked up (a passing failure)."""


def check_request(request: httpx.Request) -> None:
    """Request hook: raise unless the request's address is public.

    `BlockedAddress` for an address off the public internet, `UnresolvedAddress` (a connection
    error) for a name that could not be looked up. httpx calls request hooks before every
    request it sends, and again for every redirect hop.
    """
    reach = check_url(str(request.url))
    if reach is Reach.UNRESOLVED:
        raise UnresolvedAddress(UNREACHABLE, request=request)
    if reach is not Reach.PUBLIC:
        raise BlockedAddress("This address cannot be fetched.", request=request)


class RefusedMethod(httpx.RequestError):
    """A page-fetch client was asked to send something other than a read (GET or HEAD)."""


def read_only(request: httpx.Request) -> None:
    """Request hook for page fetching: read only, nothing personal, a fixed generic agent.

    Refuses every method but GET and HEAD (so no form is ever submitted and nothing is posted),
    removes Cookie, Authorization and Proxy-Authorization headers whatever added them, and sets
    the User-Agent to `PAGE_USER_AGENT`. httpx runs it for every request and redirect hop.
    """
    if request.method.upper() not in READ_METHODS:
        raise RefusedMethod("Only reading is allowed when fetching outside pages.", request=request)
    for name in _PERSONAL_HEADERS:
        if name in request.headers:
            del request.headers[name]
    request.headers["User-Agent"] = PAGE_USER_AGENT


def _no_cookie_jar() -> httpx.Cookies:
    """A cookie store that refuses every cookie, so nothing a site sets is ever sent back."""
    return httpx.Cookies(CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])))


def guard_client(client: httpx.Client) -> httpx.Client:
    """Make `client` a page-fetch client (in place) and return it.

    Every request the client sends, redirect hops included, goes through `check_request` (public
    addresses only) and `read_only` (GET or HEAD, no cookie or credential headers, the generic
    agent); the client stores no cookies. An address refusal also marks the client (see
    `was_blocked`) so a fetch ladder can stop trying other methods on an address that was
    refused. Redirect chains are capped at `MAX_REDIRECTS`. The client's connections are pinned
    to the checked addresses (`netpin.pin_client`), so a name cannot answer differently between
    the check and the connection. Model and service API clients that carry a key are built by
    `egress.api_client` instead and never pass through here.
    """
    if hasattr(client, "blocked"):
        return client  # already guarded: a second wrapping would only repeat every check
    client.blocked = False  # type: ignore[attr-defined]

    def hook(request: httpx.Request) -> None:
        """Run the check; remember on the client that a request was refused."""
        try:
            check_request(request)
        except BlockedAddress:
            client.blocked = True  # type: ignore[attr-defined]
            raise

    hooks = client.event_hooks
    client.event_hooks = {"request": [*hooks.get("request", []), hook, read_only],
                          "response": list(hooks.get("response", []))}
    client.cookies = _no_cookie_jar()
    client.max_redirects = MAX_REDIRECTS
    from spyglass_service.radar import netpin  # here, because netpin builds on this module

    netpin.pin_client(client)
    return client


def page_client(*, timeout: float = 25.0, follow_redirects: bool = True) -> httpx.Client:
    """The one way to build a client for fetching outside pages, feeds and search results.

    A fresh client with the generic agent, wrapped by `guard_client`: public addresses only on
    every hop, reads only, no cookies and no credential headers.
    """
    client = httpx.Client(timeout=timeout, follow_redirects=follow_redirects,
                          headers={"User-Agent": PAGE_USER_AGENT})
    return guard_client(client)


def was_blocked(client: httpx.Client) -> bool:
    """True when a guarded client has refused a request."""
    return bool(getattr(client, "blocked", False))
