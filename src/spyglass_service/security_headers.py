"""Response headers that keep a page, a framed page or a guessed file type from being turned
against the reader.

Every response from the service carries the headers below. They are constants, not settings:
the built interface is the only thing that needs different ones, and a setting would only be
a way to switch protection off by mistake.

- `X-Frame-Options: DENY` and `frame-ancestors 'none'` keep another site (or the Obsidian
  webview) from framing the interface. This ends the older interface's embedding in an Obsidian
  webview; the redesign runs standalone, so that is accepted.
- `X-Content-Type-Options: nosniff` stops a browser from treating a file as another type.
- `Referrer-Policy: no-referrer` keeps the local address and the path out of outgoing requests.
- The Content-Security-Policy confines the interface to its own scripts and connections, allows
  pictures and video from the web (articles carry them) and the YouTube and Vimeo players.

Two kinds of response are treated differently. A PDF is shown by the interface in a frame of its
own origin, so it gets `SAMEORIGIN` and `frame-ancestors 'self'` and no other policy (a full
policy on a PDF can stop the browser's PDF viewer). The MCP endpoint at `/mcp` is for programs,
not pages, so it gets no framing or content policy at all. The interactive API pages
(`/docs`, `/redoc`) load their scripts from a CDN and also get no content policy.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Written as one string so it can be read and tested as a whole. The directives:
#   default-src 'self'   everything not listed below comes only from this service
#   script-src 'self'    no inline script, no script from another site
#   style-src ... 'unsafe-inline'  the interface sets style attributes on elements
#   img-src ... data:    article pictures come from any web address; small inline images
#   media-src            video and audio in articles are fetched over https only
#   font-src ... data:   the bundled fonts, including any the build inlines
#   frame-src            the built-in PDF viewer (this service) and the two video players
#   connect-src 'self'   the interface talks only to this service
#   object-src 'none'    no plug-ins
#   base-uri, form-action  cannot be redirected by injected markup
#   frame-ancestors 'none'  nothing may frame the interface
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' http: https: data:; "
    "media-src 'self' https:; "
    "font-src 'self' data:; "
    "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com "
    "https://player.vimeo.com; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
_PDF_FRAMING = "frame-ancestors 'self'"
_NO_CSP_PREFIXES = ("/docs", "/redoc")
_NO_FRAME_POLICY_PREFIXES = ("/mcp",)


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """True when `path` is one of the prefixes or below it (`/mcp` and `/mcp/x`, not `/mcpx`)."""
    return any(path == p or path.startswith(p + "/") for p in prefixes)


class SecurityHeaders:
    """ASGI layer that adds the response headers above to every HTTP response.

    It is plain ASGI rather than `BaseHTTPMiddleware` so streamed answers (server-sent events and
    the MCP endpoint) are passed through untouched and unbuffered. A header a route already set
    is left as the route set it.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, adding the headers when the response starts."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            """Add the headers to the response start message."""
            if message["type"] == "http.response.start":
                self._apply(MutableHeaders(scope=message), path)
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    def _apply(headers: MutableHeaders, path: str) -> None:
        """Set the headers that suit this path and this response."""

        def put(name: str, value: str) -> None:
            """Set a header unless the route already did."""
            if name not in headers:
                headers[name] = value

        put("X-Content-Type-Options", "nosniff")
        put("Referrer-Policy", "no-referrer")
        if _under(path, _NO_FRAME_POLICY_PREFIXES):
            return
        if headers.get("content-type", "").lower().startswith("application/pdf"):
            put("X-Frame-Options", "SAMEORIGIN")
            put("Content-Security-Policy", _PDF_FRAMING)
            return
        put("X-Frame-Options", "DENY")
        if not _under(path, _NO_CSP_PREFIXES):
            put("Content-Security-Policy", CONTENT_SECURITY_POLICY)
