"""Settings-driven rung factories for the acquire ladder.

Extracted out of fetch_acquire.py purely to keep that module under the
project's 400-line file cap -- zero behaviour change. This module owns the rungs that
need external configuration/resources beyond a bare URL: `make_jina_rung` (T2, a
hosted renderer reached over HTTP) and `make_browser_rung` (T3, a local headless
Chromium spun up on demand), plus `build_rungs`, the Settings-driven ladder builder
that assembles curl_cffi (T1, imported from fetch_acquire) with these two behind
toggles. `fetch_acquire.acquire()` remains the sole conductor of ESCALATION; this
module only builds the rung list handed to it.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from .fetch_acquire import _acquire_curl_cffi
from .fetch_bot_check import (
    BOT_CHECK_REASON,
    frame_may_post,
    is_challenge_request,
    is_main_frame_navigation,
    registrable_domain,
    wait_out_bot_check,
    wait_seconds,
)
from .fetch_types import AcquireResult
from .radar.egress import SecretDestinationError, api_client, assert_secret_destination
from .radar.netguard import UNREACHABLE, Reach, UnpinnableHost, check_url, is_public_url
from .radar.netpin import chromium_args, curl_resolve

# URL schemes a page may still load in the headless browser: web addresses plus the
# self-contained inline ones. Anything else (file:, ftp:, chrome:) is aborted.
_BROWSER_ALLOWED_SCHEMES = frozenset({"http", "https", "data", "blob", "about"})
# The only request methods the headless browser may send.
_BROWSER_READ_METHODS = frozenset({"GET", "HEAD"})

# Jina Reader's hosted rendering endpoint: prefixing a target URL with this base and
# GETting it returns the target page rendered (JS executed) and pre-extracted to
# markdown -- clears many bot-walls/paywalls server-side that T0/T1 cannot, since the
# request originates from Jina's infrastructure, not ours. See make_jina_rung.
_JINA_READER_BASE = "https://r.jina.ai/"

# Statuses the guarded curl_cffi rung follows by hand.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _send_to_jina(request: httpx.Request) -> httpx.Response:
    """Send one request with a short-lived client bound to the rendering service's host."""
    with api_client("jina_api_key", timeout=60) as client:
        response = client.send(request)
        response.read()
        return response


def make_jina_rung(
    api_key: str | None = None,
    *,
    fetcher: Callable[[httpx.Request], httpx.Response] | None = None,
) -> Callable[[str], AcquireResult]:
    """Build the T2 rung: fetch `url` via Jina Reader (https://r.jina.ai/<url>).

    Jina Reader renders the page (JS executed) server-side and returns already-cleaned
    markdown, so a rung built by this factory hands back `kind="markdown"` -- the
    conductor (documents.fetch_fulltext) must use this payload directly and skip
    sniff_kind/the HTML extractor for it (Jina already did that work).

    `api_key` is optional -- keyless Jina Reader works at a lower (~20 req/min) rate
    limit; when present it is sent as `Authorization: Bearer <api_key>`, raising the
    limit. `fetcher` is the injectable seam: a `Callable[[httpx.Request], httpx.Response]`
    tests drive via `httpx.MockTransport` (see test_fetch_rungs.py) or the production
    default, a short-lived httpx client's `.send()` (a fresh client per call rather than
    a shared one, since this rung fires rarely -- only after T0+T1 both look blocked --
    so the extra connection setup cost is negligible next to the escalation itself).
    """

    def rung(url: str) -> AcquireResult:
        # The address leaves this computer only once the outbound guard approves it. This rung can
        # be reached without the plain fetch having checked it (a cached start tier, or a name
        # that did not resolve), so it checks for itself. The failure never repeats the address.
        if check_url(url) is not Reach.PUBLIC:
            return AcquireResult(
                payload="", kind="markdown", final_url=url, content_type="", tier="T2",
                http_status=None, error="This address cannot be sent to the rendering service.",
                ok=False,
            )
        # Jina's scheme: the target url is appended raw after the reader base -- no
        # percent-encoding of the whole url (Jina expects a normal absolute URL there).
        request = httpx.Request(
            "GET",
            f"{_JINA_READER_BASE}{url}",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
        )
        send = fetcher or _send_to_jina
        try:
            # The rendering service's key may only go to the rendering service.
            assert_secret_destination("jina_api_key", str(request.url))
            response = send(request)
        except (httpx.HTTPError, SecretDestinationError) as error:  # a rung failure is data
            return AcquireResult(
                payload="", kind="markdown", final_url=url, content_type="", tier="T2",
                http_status=None, error=str(error), ok=False,
            )

        if response.status_code != 200:
            return AcquireResult(
                payload="", kind="markdown", final_url=url, content_type="", tier="T2",
                http_status=response.status_code,
                error=f"HTTP {response.status_code}", ok=False,
            )

        return AcquireResult(
            payload=response.text,
            kind="markdown",
            final_url=url,
            content_type="text/markdown",
            tier="T2",
            http_status=response.status_code,
            error=None,
            ok=True,
        )

    # Declared tier tag: acquire()'s start_tier skip reads this attribute (falling
    # back to ladder position only when it's absent) so the skip stays correct even
    # when build_rungs omits a lower rung (e.g. Jina disabled) -- see fetch_acquire.py.
    rung.tier = "T2"
    return rung


def make_request_guard(*, allow_bot_checks: bool = False, page_url: str | None = None) -> Callable:
    """Build the request handler for ONE browser page: reads only, public internet only.

    The handler is registered for every request the headless page makes -- the navigation itself,
    its redirects and every sub-resource -- so a public page cannot make the local browser read
    this computer or a private network. A web address is allowed only when `is_public_url`
    accepts its host (literal private addresses, internal suffixes and names that resolve to a
    private address are refused). Each host is resolved once per page: the verdicts are kept in
    a dict owned by the returned handler, so a page with hundreds of sub-resources does not
    trigger hundreds of lookups. Schemes other than web and inline ones are aborted.

    Only GET and HEAD are let through. With `allow_bot_checks`, a non-read request may also go to
    the checking service's challenge endpoints for the page's own domain (`page_url` and every
    page the MAIN frame navigates to; an embedded frame never adds one), and only when the
    request comes from a frame on that domain or from the checking service's host (see fetch_bot_check).
    """
    verdicts: dict[str, bool] = {}
    page_domains = {registrable_domain(urlsplit(page_url).hostname or "")} if page_url else set()

    def handler(route, request) -> None:
        """Continue the request when it is a read of an allowed target, abort it otherwise."""
        # Only the top-level frame's navigations (the page and its redirects) name the page's own
        # domains; a frame the page embeds is controlled by the page and must not widen them.
        if is_main_frame_navigation(request):
            page_domains.add(registrable_domain(urlsplit(request.url).hostname or ""))
        # Reads only: a form post, beacon or script write from the page is never sent, except
        # (when the reader switched it on) to the checking service's own challenge endpoint, and
        # then only from a frame on the page's own domain or the checking service's host.
        if str(getattr(request, "method", "GET")).upper() not in _BROWSER_READ_METHODS and not (
                allow_bot_checks and is_challenge_request(request.url, page_domains)
                and frame_may_post(request, page_domains)):
            route.abort()
            return
        parts = urlsplit(request.url)
        scheme = parts.scheme.lower()
        if scheme in ("http", "https"):
            host = (parts.hostname or "").lower()
            if host not in verdicts:
                # Judged on the bare host so one verdict serves every path on it.
                verdicts[host] = bool(host) and is_public_url(f"{scheme}://{host}/")
            allowed = verdicts[host]
        else:
            allowed = scheme in _BROWSER_ALLOWED_SCHEMES
        if allowed:
            route.continue_()
        else:
            route.abort()

    return handler


def make_websocket_guard() -> Callable:
    """Build the WebSocket handler for ONE browser page: only public hosts may be connected to.

    `page.route` never sees WebSocket connections, so a page could open one to this computer or
    a private network. Playwright's `route_web_socket` hands each connection to this handler,
    which closes it unless its host passes `is_public_url` (judged on the bare host, once).
    """
    verdicts: dict[str, bool] = {}

    def handler(ws) -> None:
        """Connect the page's WebSocket to its server when allowed; close it otherwise."""
        parts = urlsplit(ws.url)
        host = (parts.hostname or "").lower()
        if host not in verdicts:
            scheme = "https" if parts.scheme.lower() == "wss" else "http"
            verdicts[host] = bool(host) and is_public_url(f"{scheme}://{host}/")
        if verdicts[host]:
            ws.connect_to_server()
        else:
            ws.close(code=1008, reason="blocked")

    return handler


def open_guarded_page(browser, *, allow_bot_checks: bool = False, page_url: str | None = None):
    """A new page in its own fresh context with every request, WebSocket and service worker guarded.

    The context starts empty (no stored cookies or storage), grants no permission (location,
    notifications, clipboard, camera and microphone stay denied), refuses downloads and uses a
    fixed language and time zone instead of this computer's. Service workers are blocked because
    their fetches bypass `page.route`; the page's requests and WebSockets go through the guards
    above, and only reads (GET and HEAD) are let through (plus, with `allow_bot_checks`, writes
    to the checking service's challenge endpoints for `page_url`'s domain).
    """
    context = browser.new_context(
        service_workers="block", storage_state=None, permissions=[], accept_downloads=False,
        locale="en-US", timezone_id="UTC")
    page = context.new_page()
    page.route("**/*", make_request_guard(allow_bot_checks=allow_bot_checks, page_url=page_url))
    page.route_web_socket(lambda _url: True, make_websocket_guard())  # every socket
    return page


def make_guarded_curl_rung(max_hops: int = 5) -> Callable[[str], AcquireResult]:
    """The T1 rung with redirects followed by hand, every hop checked before it is requested.

    curl_cffi follows redirects itself, which would carry a request from a public address to a
    private one unseen. This rung asks it not to, reads each `Location`, and refuses a hop that
    `check_url` does not find public (or a chain longer than `max_hops` redirects), returning a
    failed result and never requesting that hop. A name that could not be looked up is reported
    as a passing failure (`UNREACHABLE`). Each request is pinned to the addresses just checked
    (curl's resolve option), so curl does not look the name up a second time.
    """

    def failure(url: str, message: str) -> AcquireResult:
        """A failed T1 result with no HTTP status."""
        return AcquireResult(payload=b"", kind="bytes", final_url=url, content_type="", tier="T1",
                             http_status=None, error=message, ok=False)

    def rung(url: str) -> AcquireResult:
        current = url
        for _ in range(max_hops + 1):
            reach = check_url(current)
            if reach is Reach.UNRESOLVED:
                return failure(url, UNREACHABLE)
            if reach is not Reach.PUBLIC:
                return failure(url, "This address cannot be fetched.")
            try:
                # Connect to the addresses just checked, not to a fresh lookup of the name.
                resolve = curl_resolve(current)
            except UnpinnableHost as exc:
                return failure(url, str(exc))
            result = _acquire_curl_cffi(current, follow_redirects=False, resolve=resolve)
            if result.http_status not in _REDIRECT_STATUSES or result.error != "redirect":
                return result
            current = result.final_url
        return failure(url, "The address redirected too many times.")

    rung.tier = "T1"
    return rung


def finish_render(page, wait_s: float) -> str:
    """The rendered HTML of a page that has been navigated, once any automated check is gone.

    Waits up to `wait_s` for an interstitial to clear; raises RuntimeError with
    `BOT_CHECK_REASON` when it does not, or when the page ended on a non-public address.
    """
    if not wait_out_bot_check(page, wait_s):
        raise RuntimeError(BOT_CHECK_REASON)
    # Redirects were each judged by the guard; the page must also END on a public address.
    if not is_public_url(page.url):
        raise RuntimeError("the page ended on a non-public address")
    return page.content()


def make_browser_rung(
    *,
    renderer: Callable[[str], str] | None = None,
    allow_bot_checks: bool = False,
) -> Callable[[str], AcquireResult]:
    """Build the T3 rung: render `url` in a local headless Chromium via patchright.

    This is the last-resort local tier -- for pages that are JS-gated or bot-walled
    past T0 (httpx)/T1 (curl_cffi)/T2 (Jina Reader), a real (stealth-patched) browser
    is spun up on demand, navigates to the page, and hands back the fully rendered
    HTML, then is torn down. Unlike Jina, this never leaves the machine (no
    third-party sees the URL) at the cost of being slower and heavier per call.

    A rung built by this factory hands back `kind="html"` -- a decoded str of
    rendered markup that still needs the HTML extractor (unlike Jina's `kind=
    "markdown"`, which is already pre-extracted). The conductor
    (documents.fetch_fulltext) must route `kind=="html"` straight into
    extract_markdown, skipping sniff_kind/charset-decode (the payload is already a
    str, not bytes).

    `renderer` is the injectable seam: `Callable[[str], str]` (url -> rendered HTML).
    Tests pass a canned-HTML stub -- NO real browser/Chromium in any unit test. The
    production default lazily imports patchright INSIDE this closure (not at module
    top), so the import only happens when this rung actually fires (rarely -- only
    after T0-T2 all look blocked) and unrelated tests never pay patchright's import
    cost or trip any import-time warning under this project's `filterwarnings =
    ["error"]` pytest setting (mirrors the curl_cffi/trafilatura lazy-import pattern
    used elsewhere in this codebase).

    `allow_bot_checks` is the reader's `privacy_allow_bot_checks` switch (see fetch_bot_check):
    off, the page sends reads only and an interstitial gets 8 seconds to clear on its own; on,
    the checking service's challenge endpoints may also receive the check's data, for 20 seconds.
    """

    def _default_renderer(url: str) -> str:
        """Render `url` in a fresh headless Chromium, torn down after this one page."""
        from patchright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            # Local-network checks on, and the page's own host resolved to its checked address.
            browser = playwright.chromium.launch(headless=True, args=chromium_args(url))
            try:
                page = open_guarded_page(browser, allow_bot_checks=allow_bot_checks, page_url=url)
                page.goto(url, timeout=60000)
                return finish_render(page, wait_seconds(allow_bot_checks))
            finally:
                browser.close()

    def rung(url: str) -> AcquireResult:
        render = renderer or _default_renderer
        try:
            html = render(url)
        except Exception as error:  # noqa: BLE001 -- patchright raises its own error
            # hierarchy (launch failure, navigation timeout, Chromium not installed,
            # ...); a rung failure must be data, never a crash that takes down acquire().
            return AcquireResult(
                payload="", kind="html", final_url=url, content_type="", tier="T3",
                http_status=None, error=str(error), ok=False,
            )

        if not html.strip():
            # A "successful" render with nothing usable is still a failed rung -- an
            # empty page is no better than a block, and handing it back as ok=True
            # would make the conductor report a hollow "ok"/empty extraction instead
            # of a clear failure to escalate from.
            return AcquireResult(
                payload="", kind="html", final_url=url, content_type="", tier="T3",
                http_status=None, error="empty render", ok=False,
            )

        return AcquireResult(
            payload=html,
            kind="html",
            final_url=url,
            content_type="text/html",
            tier="T3",
            http_status=200,
            error=None,
            ok=True,
        )

    # Declared tier tag -- see the matching comment in make_jina_rung above.
    rung.tier = "T3"
    return rung


def build_rungs(
    settings, target_kind: str = "html", *, guarded: bool = True,
) -> tuple[Callable[[str], AcquireResult], ...]:
    """The production ladder as configured by `settings` and `target_kind`.

    Always includes curl_cffi (T1). Appends the Jina Reader rung (T2) iff
    `settings.jina_enabled` -- kind-agnostic (Jina stays in a PDF/image ladder too).
    Appends the browser rung (T3, patchright) iff BOTH `settings.browser_enabled` AND
    `target_kind == "html"` -- unlike Jina, the browser tier is HTML-ONLY by construction:
    a PDF/image ladder never contains it, since rendering a PDF or image URL in a browser
    buys nothing a byte-fetch didn't already get. By default (`guarded=True`) the curl_cffi rung
    follows redirects by hand and checks every hop (`make_guarded_curl_rung`); `guarded=False` is
    only for tests of the raw rung.
    """
    rungs: tuple[Callable[[str], AcquireResult], ...] = (
        (make_guarded_curl_rung() if guarded else _acquire_curl_cffi),)
    if settings.jina_enabled:
        rungs = rungs + (make_jina_rung(settings.jina_api_key),)
    if settings.browser_enabled and target_kind == "html":
        rungs = rungs + (make_browser_rung(
            allow_bot_checks=bool(getattr(settings, "privacy_allow_bot_checks", False))),)
    return rungs
