"""Follow a link's redirects by hand, checking every address before it is requested.

The engine's fetch ladder lets its HTTP client follow redirects on its own, so a public link
could bounce the request to this computer or a private network before anything checks the
address. This pre-flight walks the chain first, one streamed request per hop, and refuses the
chain as soon as a hop leaves the public internet. Response bodies are never read.

The pre-flight is an early exit, not the guarantee: a server can answer the real request
differently from this one. It fails closed (an error, a timeout or a chain longer than
`MAX_HOPS` redirects refuses the link), and the fetch that follows is guarded structurally
(`netguard.guard_client`, `fetch_rungs.make_guarded_curl_rung`).
"""

import logging
from typing import NamedTuple
from urllib.parse import urljoin

import httpx

from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

# Redirects followed by hand. A longer chain is refused; five covers every ordinary tracking or
# shortener chain.
MAX_HOPS = 5
# Seconds allowed for each pre-flight request: it only needs the response headers.
PREFLIGHT_TIMEOUT = 8.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class RedirectOutcome(NamedTuple):
    """Where a link leads: the last address that passed the check, and whether a hop was refused.

    `transient` is True when the walk stopped for a passing reason (a network error, a time-out
    or a host name that could not be looked up) rather than a refused address; the link is still
    not fetched, but the failure should not be remembered as lasting.
    """

    url: str
    blocked: bool = False
    transient: bool = False


def resolve_redirects(client: httpx.Client, url: str) -> RedirectOutcome:
    """Walk `url`'s redirect chain (at most MAX_HOPS redirects) and return where it ends.

    `url` must already have passed `netguard.is_public_url`. The walk fails closed: a hop whose
    address is not public, a network error or time-out, and a chain longer than MAX_HOPS all
    return `blocked=True`, and the refused hop is never requested.
    """
    current = url
    for _ in range(MAX_HOPS + 1):
        try:
            with client.stream("GET", current, follow_redirects=False,
                               timeout=PREFLIGHT_TIMEOUT) as response:
                location = response.headers.get("location")
                is_redirect = response.status_code in _REDIRECT_STATUSES and bool(location)
        except netguard.BlockedAddress:
            return RedirectOutcome(current, blocked=True)
        except httpx.HTTPError as exc:
            # A network error, a time-out or an unresolved name: refused for now, not for good.
            logger.info("redirect pre-flight failed at %s: %s", current, exc.__class__.__name__)
            return RedirectOutcome(current, blocked=True, transient=True)
        if not is_redirect:
            return RedirectOutcome(current)
        target = urljoin(current, location)
        reach = netguard.check_url(target)
        if reach is not netguard.Reach.PUBLIC:
            return RedirectOutcome(current, blocked=True,
                                   transient=reach is netguard.Reach.UNRESOLVED)
        current = target
    return RedirectOutcome(current, blocked=True)
