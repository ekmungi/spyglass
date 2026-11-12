"""Guards for endpoints a web page must not be able to call.

A page in the user's browser can send a "simple" cross-site POST (no preflight), and the browser
puts that page's own address in an `Origin` header. The CORS setting only stops the page from
reading the reply; the request still runs. So the service refuses state-changing
requests that name any other site (`CrossSiteGuard`), and the endpoints that open a Claude session
with text in it, or change what the linked session sees, also insist on an `application/json`
body (`require_json`), which a foreign page cannot send without a refused CORS preflight.
"""

import re

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# The sites allowed to call this service from a browser: the Obsidian app, and a local browser
# tab on any port. The CORS setting in app.py reads these same two values, so the two cannot
# drift apart.
ALLOWED_ORIGIN = "app://obsidian.md"
ALLOWED_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?"
_LOCAL_ORIGIN = re.compile(ALLOWED_ORIGIN_REGEX)

# Methods that change nothing. A foreign page may send these; CORS keeps it from reading the reply.
_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REFUSAL = "cross-site request refused"
# (method, exact path) pairs another site may send. The only one is the "Send to Spyglass" bookmark
# button's fallback: a form submitted from the page the reader is reading, so it necessarily comes
# from that page's site. The route only parks the page in a bounded, expiring staging folder and
# redirects to a fixed address on this service; nothing is imported, fetched or changed until the
# reader confirms in Spyglass itself, through routes that stay guarded. The path must match exactly
# (no prefix, no trailing slash), so no other route can borrow the exemption.
#
# The second pair is the "Send to Spyglass" browser extension's import. An extension's requests
# carry a `chrome-extension://` origin, which this guard would refuse. The protection there is the
# per-install key in the `X-Spyglass-Key` header: the route refuses the request without it (a web
# page does not have it, and sending a custom header needs a CORS preflight that this service
# refuses to every site but Obsidian and local pages), and it also refuses any web-page origin.
CROSS_SITE_EXEMPT = frozenset({("POST", "/api/radar/import/stage"), ("POST", "/api/radar/import/direct")})


def origin_allowed(origin: str) -> bool:
    """Whether an `Origin` header value names the Obsidian app or a local browser tab.

    The whole value must match: a look-alike such as `http://localhost.evil.example`, the string
    `null` (sent by sandboxed pages) and an empty value are all refused.
    """
    return origin == ALLOWED_ORIGIN or _LOCAL_ORIGIN.fullmatch(origin) is not None


class CrossSiteGuard:
    """ASGI layer that refuses a POST, PUT, PATCH or DELETE sent from another site (403).

    A request with no `Origin` header is let through: browsers always send one on a cross-site
    POST, while the Obsidian plugin, Claude, PowerShell and scripts send none. The routes in
    `CROSS_SITE_EXEMPT` are let through from any site. It is plain ASGI rather than
    `BaseHTTPMiddleware` so the streaming MCP endpoint is left alone.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and scope["method"] not in _READ_ONLY_METHODS
                and (scope["method"], scope.get("path")) not in CROSS_SITE_EXEMPT):
            origins = [value.decode("latin-1") for name, value in scope["headers"]
                       if name == b"origin"]
            if not all(origin_allowed(origin) for origin in origins):
                response = JSONResponse({"detail": REFUSAL}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def require_json(request: Request) -> None:
    """Refuse a body that is not declared as JSON (415)."""
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("application/json"):
        raise HTTPException(status_code=415, detail="send the body as application/json")
