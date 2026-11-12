"""One normal form for an article's address, so the same article stored twice is one source.

Feeds, searches and the reader's captures can store one article under slightly different
addresses: http or https, a "www." prefix, capitals in the host, a trailing slash, tracking
parameters, a fragment. A Google News link is replaced by the publisher's address once it is
resolved (see `sources.google_links`), after which it normalises like any other address.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit

# Query parameters that only track the sender.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "mkt_tok",
                      "ref_src", "cmpid", "ocid")


def normalize_address(url: str | None) -> str:
    """The comparable form of an address, or "" when there is none.

    Ignores the scheme, a leading "www.", the host's capitals, the default port, a trailing
    slash, the fragment, tracking parameters and the order of the other parameters.
    """
    text = (url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return text.lower()
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return text.lower()
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if not k.lower().startswith(_TRACKING_PREFIXES))
    path = parts.path.rstrip("/")
    return f"{netloc}{path}" + (f"?{urlencode(query)}" if query else "")
