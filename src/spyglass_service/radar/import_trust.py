"""Whether the site that sent a page is the site the page says it is from.

The "Send to Spyglass" button hands over a page together with the address it claims. The browser
tells the service who really sent it (the sender's origin), so the two can be compared: a page
sent from `evil.example` that claims to be from `news.example.com` must be said so, and must not
be able to replace an article the reader already has.

Two hosts are the same site when they share a registrable domain (`www.example.com` and
`news.example.com` do; `example.com` and `example.org` do not). Literal IP addresses are the same
site only when they are identical. The registrable domain is approximate (see fetch_bot_check):
unusual public suffixes count as one site.

That approximate comparison is used only for WORDING (whether to say "sent by another site" and
what to show as the publication). Whether a page may REPLACE an article the reader already has is
decided by `may_replace`, which compares exact hosts (ignoring only case and a leading `www.`), so
two unrelated sites under one shared hosting suffix can never replace each other's articles.
"""

import ipaddress
from urllib.parse import urlsplit

from spyglass_service.fetch_bot_check import registrable_domain

UNKNOWN_SENDER = "unknown site"
REPLACE_REFUSED = "A page sent from another site cannot replace an article you already have."


def host_of(address: str | None) -> str | None:
    """The lower-case host of an origin or address, or None when there is none."""
    host = urlsplit((address or "").strip()).hostname
    return host.lower().rstrip(".") if host else None


def _is_ip(host: str) -> bool:
    """Whether `host` is a literal IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def same_site(sender_host: str | None, claimed_host: str | None) -> bool:
    """True when both hosts are known and share a registrable domain (IP addresses: identical)."""
    if not sender_host or not claimed_host:
        return False
    if _is_ip(sender_host) or _is_ip(claimed_host):
        return sender_host == claimed_host
    return registrable_domain(sender_host) == registrable_domain(claimed_host)


def _exact(host: str | None) -> str | None:
    """`host` in lower case without a leading "www." (None stays None)."""
    if not host:
        return None
    return host[4:] if host.startswith("www.") and len(host) > 4 else host


def may_replace(sender: str | None, address: str) -> bool:
    """True when the sender's host is exactly the address's host (ignoring case and "www.").

    The honest button sends the page's own address, so its sender is always that host. Any other
    sender (a sibling sub-domain included) may not replace an article that already exists.
    """
    sender_host, claimed_host = _exact(host_of(sender)), _exact(host_of(address))
    return sender_host is not None and sender_host == claimed_host


def foreign_sender(sender: str | None, address: str) -> str | None:
    """The sender's host when it does NOT match the address's site, else None.

    A page staged without a known sender counts as foreign and is named `UNKNOWN_SENDER`.
    """
    sender_host = host_of(sender)
    if same_site(sender_host, host_of(address)):
        return None
    return sender_host or UNKNOWN_SENDER
