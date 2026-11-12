"""Address guard for the `requests` sessions of the feed library.

The feed library (`reader`) fetches feeds with its own `requests` session, which `netguard`'s httpx
wrapper cannot reach. `guard_retriever` mounts `GuardedAdapter` on that session. An adapter sees
every request the session sends, redirect hops included, so the rule is the same as for page
fetching and cannot be skipped by a feed that redirects:

- the address must be public (`netguard.check_url`: http(s), no user info, no internal name, a
  public answer from DNS), otherwise the request is refused before any connection is made;
- the socket is opened to an address that passed that check (`Pinned*Connection`), so a name that
  answers differently a moment later (DNS rebinding) cannot reach a private address, while TLS
  still checks the certificate against the name.

Requests that go through a configured proxy are resolved by the proxy and are not pinned here, as
for `netpin`. The refusal reasons are the plain ones `netguard` uses.
"""

import logging
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

# The reason shown when an address is refused (also what the feed registry shows the reader).
REFUSED = "This address cannot be fetched."


class BlockedFeedAddress(requests.exceptions.ConnectionError):
    """A feed request was refused because its address is not on the public internet."""


def _connect_to_checked(connection: HTTPConnection, connect) -> socket.socket:
    """Open `connection` to the first checked address that answers; `connect` is the real opener.

    The connection's `_dns_host` is the name urllib3 resolves and, via `host`, the name TLS
    verifies. It is swapped for an approved address only while the socket is opened.
    """
    name = connection._dns_host  # noqa: SLF001 -- no public hook exists for this
    try:
        addresses = netguard.checked_addresses(name)
    except netguard.UnpinnableHost as exc:
        raise NewConnectionError(connection, str(exc)) from exc
    last: Exception | None = None
    for address in addresses:
        connection._dns_host = address  # noqa: SLF001
        try:
            return connect()
        except (NewConnectionError, ConnectTimeoutError) as exc:
            last = exc
        finally:
            connection._dns_host = name  # noqa: SLF001
    raise last or NewConnectionError(connection, "no approved address answered")


class PinnedHTTPConnection(HTTPConnection):
    """A plain connection that opens its socket to a checked address."""

    def _new_conn(self) -> socket.socket:
        """Open the socket to an address that passed the public-address check."""
        return _connect_to_checked(self, super()._new_conn)


class PinnedHTTPSConnection(HTTPSConnection):
    """A TLS connection that opens its socket to a checked address (the name is still verified)."""

    def _new_conn(self) -> socket.socket:
        """Open the socket to an address that passed the public-address check."""
        return _connect_to_checked(self, super()._new_conn)


class _PinnedHTTPPool(HTTPConnectionPool):
    """Connection pool for http:// that builds pinned connections."""

    ConnectionCls = PinnedHTTPConnection


class _PinnedHTTPSPool(HTTPSConnectionPool):
    """Connection pool for https:// that builds pinned connections."""

    ConnectionCls = PinnedHTTPSConnection


class GuardedAdapter(HTTPAdapter):
    """An adapter that checks every request's address and connects only to checked addresses."""

    def __init__(self, timeout: float | tuple[float, float] | None = None, *args, **kwargs) -> None:
        """`timeout` is applied to requests that give none, as the feed library's own adapter does."""
        self._default_timeout = timeout
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs) -> None:
        """Build the pool manager, then make it use the pinned connection pools."""
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PinnedHTTPPool, "https": _PinnedHTTPSPool}

    def send(self, request: requests.PreparedRequest, **kwargs):
        """Refuse a non-public address, otherwise send; runs for the first request and each redirect."""
        reach = netguard.check_url(request.url or "")
        if reach is not netguard.Reach.PUBLIC:
            host = urlsplit(request.url or "").hostname or "?"
            logger.warning("feed request refused (%s): %s", reach.value, host)
            if reach is netguard.Reach.UNRESOLVED:
                raise requests.exceptions.ConnectionError(netguard.UNREACHABLE, request=request)
            raise BlockedFeedAddress(REFUSED, request=request)
        if self._default_timeout is not None:
            kwargs.setdefault("timeout", self._default_timeout)
        return super().send(request, **kwargs)


def guard_session(session: requests.Session, timeout: float | tuple[float, float] | None = None) -> None:
    """Mount `GuardedAdapter` for http:// and https:// on `session` (in place)."""
    adapter = GuardedAdapter(timeout)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
