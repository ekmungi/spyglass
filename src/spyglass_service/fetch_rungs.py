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

import httpx

from .fetch_acquire import _acquire_curl_cffi
from .fetch_types import AcquireResult

# Jina Reader's hosted rendering endpoint: prefixing a target URL with this base and
# GETting it returns the target page rendered (JS executed) and pre-extracted to
# markdown -- clears many bot-walls/paywalls server-side that T0/T1 cannot, since the
# request originates from Jina's infrastructure, not ours. See make_jina_rung.
_JINA_READER_BASE = "https://r.jina.ai/"


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
        # Jina's scheme: the target url is appended raw after the reader base -- no
        # percent-encoding of the whole url (Jina expects a normal absolute URL there).
        request = httpx.Request(
            "GET",
            f"{_JINA_READER_BASE}{url}",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
        )
        send = fetcher or (lambda req: httpx.Client(timeout=60).send(req))
        try:
            response = send(request)
        except httpx.HTTPError as error:  # a rung failure is data, never a crash
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


def make_browser_rung(
    *,
    renderer: Callable[[str], str] | None = None,
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
    """

    def _default_renderer(url: str) -> str:
        """Render `url` in a fresh headless Chromium, torn down after this one page."""
        from patchright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=60000)
                return page.content()
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
    settings, target_kind: str = "html",
) -> tuple[Callable[[str], AcquireResult], ...]:
    """The production ladder as configured by `settings` and `target_kind`.

    Always includes curl_cffi (T1). Appends the Jina Reader rung (T2) iff
    `settings.jina_enabled` -- kind-agnostic (Jina stays in a PDF/image ladder too).
    Appends the browser rung (T3, patchright) iff BOTH `settings.browser_enabled` AND
    `target_kind == "html"` -- unlike Jina, the browser tier is HTML-ONLY by construction:
    a PDF/image ladder never contains it, since rendering a PDF or image URL in a browser
    buys nothing a byte-fetch didn't already get.
    """
    rungs: tuple[Callable[[str], AcquireResult], ...] = (_acquire_curl_cffi,)
    if settings.jina_enabled:
        rungs = rungs + (make_jina_rung(settings.jina_api_key),)
    if settings.browser_enabled and target_kind == "html":
        rungs = rungs + (make_browser_rung(),)
    return rungs
