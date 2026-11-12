"""Pin connections to the addresses the address check approved.

`netguard` checks a host name before a request is sent, and the HTTP library then looks the name
up again to connect. A name that changes its answer between the two (DNS rebinding) could reach a
private address. This module makes each fetching path connect to the checked addresses instead:

- httpx (page fetching): `PinnedBackend` replaces the connection pool's network backend, so the
  socket goes to an address from `netguard.checked_addresses` while TLS still checks the
  certificate against the host name. `pin_client` installs it on a guarded client.
- curl_cffi (the browser-like rung): `curl_resolve` gives curl's resolve entries
  (`host:port:address,...`) so curl uses the checked addresses.
- the headless browser: `chromium_args` turns on Chromium's local-network checks (requests from
  a public page to a private address are blocked) and maps the page's own host to its checked
  address. Other hosts the page loads are still resolved by the browser, and checked by the
  request guard, so for those the gap remains (narrowed by the local-network checks).

Requests that go through a configured proxy are resolved by the proxy and are not pinned here.
"""

import logging

import httpcore
import httpx

from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

# Chromium features that block requests from public pages to private and local addresses
# (checked against the bundled Chromium 149 build).
LOCAL_NETWORK_FEATURES = "LocalNetworkAccessChecks,LocalNetworkAccessChecksWebSockets"


def _host_port(url: str) -> tuple[str, int]:
    """The lower-case host and the port (default for the scheme) of a URL."""
    parts = httpx.URL(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return (parts.host or "").lower(), port


def curl_resolve(url: str) -> list[str] | None:
    """curl's resolve entries pinning `url`'s host to its checked addresses; None for a literal.

    Raises `netguard.UnpinnableHost` when the host has no approved public address.
    """
    host, port = _host_port(url)
    addresses = netguard.checked_addresses(host)
    if addresses == [host.strip("[]")]:
        return None
    joined = ",".join(f"[{a}]" if ":" in a else a for a in addresses)
    return [f"{host}:{port}:{joined}"]


def chromium_args(url: str) -> list[str]:
    """Launch arguments for the headless browser rendering `url`.

    Always the local-network checks; plus a resolver rule mapping the page's host to its first
    checked address, when the host is a name with an approved public address.
    """
    args = [f"--enable-features={LOCAL_NETWORK_FEATURES}"]
    host, _port = _host_port(url)
    try:
        addresses = netguard.checked_addresses(host)
    except netguard.UnpinnableHost:
        return args  # the request guard refuses the page itself
    if addresses != [host.strip("[]")]:
        first = addresses[0]
        args.append(f"--host-resolver-rules=MAP {host} {f'[{first}]' if ':' in first else first}")
    return args


class PinnedBackend(httpcore.SyncBackend):
    """A network backend that connects only to the addresses the address check approved."""

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options=None) -> httpcore.NetworkStream:
        """Connect to the first approved address that answers; raise when none is approved.

        The host name is kept by the caller for the TLS handshake, so the certificate is still
        checked against the name, not the address.
        """
        addresses = netguard.checked_addresses(host)  # raises UnpinnableHost (a ConnectError)
        last: Exception | None = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout=timeout,
                                           local_address=local_address,
                                           socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                last = exc
        raise httpcore.ConnectError(f"no approved address answered: {last}")


def pin_client(client: httpx.Client) -> bool:
    """Install `PinnedBackend` on a client's own connection pool; False when it has none.

    A test client (a mock transport) has no pool and needs none. The pool's backend is not a
    public setting of httpx, so a change of library version that moves it is logged loudly (and
    caught by the tests) rather than silently leaving connections unpinned.
    """
    pool = getattr(getattr(client, "_transport", None), "_pool", None)
    if pool is None:
        return False
    if not hasattr(pool, "_network_backend"):
        logger.error("httpx changed: connections cannot be pinned to checked addresses")
        return False
    pool._network_backend = PinnedBackend()  # noqa: SLF001 -- no public setting exists
    return True


def is_pinned(client: httpx.Client) -> bool:
    """True when the client's own pool connects through `PinnedBackend`."""
    pool = getattr(getattr(client, "_transport", None), "_pool", None)
    return isinstance(getattr(pool, "_network_backend", None), PinnedBackend)
