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


def origin_allowed(origin: str) -> bool:
    """Whether an `Origin` header value names the Obsidian app or a local browser tab.

    The whole value must match: a look-alike such as `http://localhost.evil.example`, the string
    `null` (sent by sandboxed pages) and an empty value are all refused.
    """
    return origin == ALLOWED_ORIGIN or _LOCAL_ORIGIN.fullmatch(origin) is not None


class CrossSiteGuard:
    """ASGI layer that refuses a POST, PUT, PATCH or DELETE sent from another site (403).

    A request with no `Origin` header is let through: browsers always send one on a cross-site
    POST, while the Obsidian plugin, Claude, PowerShell and scripts send none. It is plain ASGI
    rather than `BaseHTTPMiddleware` so the streaming MCP endpoint is left alone.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in _READ_ONLY_METHODS:
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
