"""How Spyglass fetches feeds: with a browser's User-Agent, and with plain reasons.

The reader library's default agent ("python-reader/...") is refused by sites that block unknown
clients, so adding such a feed failed with "not a feed" while page fetching (documents.py) and
feed discovery, which send a browser-like agent, worked. Every reader instance Spyglass makes now
sends the same browser-like agent. When a feed still fails, the reason is told apart: the site
refused, the address could not be reached, or it answered with something that is not a feed.
"""

import re

# Browser-like UA: many article/paper hosts 403 default library agents (python-httpx, reader).
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 Spyglass/0.1"
)

REASONS = {
    "blocked": "The site refused Spyglass (it may block automated readers).",
    "unreachable": "Spyglass could not reach the address (no connection, a timeout, or a "
    "certificate problem).",
    "not_a_feed": "The address answered, but not with a feed. If it is a website, use Discover "
    "to find its feeds.",
}

_BLOCKED_CODES = (401, 403, 429)
# requests' HTTPError text, e.g. "403 Client Error: Forbidden for url: ..."
_STATUS = re.compile(r"\b(\d{3}) (?:client|server) error", re.IGNORECASE)
_UNREACHABLE_MARKERS = (
    "timeout", "timed out", "connectionerror", "connection refused", "max retries",
    "name or service not known", "nameresolution", "getaddrinfo", "sslerror", "certificate",
)


def use_browser_user_agent(reader) -> None:
    """Make every request of this reader instance send the browser-like agent.

    Uses the parser's lazy-init hook and get_retriever, the way reader's own ua_fallback plugin
    configures its retrievers; its 403 fallback keeps working on top of this agent.
    """

    def init(parser) -> None:
        for scheme in ("http://", "https://"):
            retriever = parser.get_retriever(scheme)
            retriever.user_agent = BROWSER_USER_AGENT
            # The retriever copies user_agent onto its requests session when it is built, so the
            # session header is what actually goes on the wire.
            retriever.session.headers["User-Agent"] = BROWSER_USER_AGENT

    reader._parser.lazy_init(init)


def classify_feed_error(detail: str) -> tuple[str, str]:
    """Why a feed could not be read, as (kind, reason): blocked, unreachable or not_a_feed.

    reader records every failure as a ParseError, so the kind comes from the message and
    traceback it keeps: "bad HTTP status code" with the status, "while getting feed" with the
    network error, or "unknown feed type" for a page that is not a feed.

    Args:
        detail: The recorded exception's message and traceback text.
    """
    text = detail.lower()
    status = _STATUS.search(detail)
    if status or "bad http status code" in text:
        code = int(status.group(1)) if status else None
        if code in _BLOCKED_CODES:
            return "blocked", f"{REASONS['blocked'][:-1]} (HTTP {code})."
        shown = f" (HTTP {code})" if code else ""
        return "unreachable", f"The site answered with an error{shown}. Check the address."
    if any(marker in text for marker in _UNREACHABLE_MARKERS):
        return "unreachable", REASONS["unreachable"]
    return "not_a_feed", REASONS["not_a_feed"]
