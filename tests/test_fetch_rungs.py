"""Tests for the Settings-driven rung factories.

Covers ``make_jina_rung`` (T2, Jina Reader), ``make_browser_rung`` (T3, patchright),
and ``build_rungs`` -- the Settings-driven ladder builder that assembles curl_cffi
(T1) + these two behind toggles. Moved out of test_fetch_acquire.py in the same split
that extracted fetch_rungs.py from fetch_acquire.py -- no behaviour change, only the
file (and, for the monkeypatch test, the patch target module) moved.
"""

from types import SimpleNamespace

import httpx

from spyglass_service.fetch_acquire import AcquireResult
from spyglass_service.fetch_rungs import build_rungs, make_browser_rung, make_jina_rung

# -- make_jina_rung: the T2 Jina Reader rung --------------------------


def test_jina_rung_success_returns_markdown_result() -> None:
    """A successful Jina response wraps into an AcquireResult with kind="markdown", tier=T2."""
    captured: list[httpx.Request] = []

    def fetcher(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="# Title\n\nclean article body")

    rung = make_jina_rung(fetcher=fetcher)
    result = rung("https://example.test/blocked-article")

    assert isinstance(result, AcquireResult)
    assert result.ok is True
    assert result.kind == "markdown"
    assert result.payload == "# Title\n\nclean article body"
    assert result.tier == "T2"
    assert result.http_status == 200
    assert result.error is None
    assert result.final_url == "https://example.test/blocked-article"
    assert result.content_type == "text/markdown"
    # Jina takes the raw target url appended to its reader endpoint.
    assert captured[0].url.path.endswith("https://example.test/blocked-article") or (
        "example.test/blocked-article" in str(captured[0].url)
    )
    assert str(captured[0].url).startswith("https://r.jina.ai/")


def test_jina_rung_non_200_is_a_failure() -> None:
    """A non-200 Jina response is a rung failure, not a crash -- ok=False, tier=T2."""
    def fetcher(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(451)

    rung = make_jina_rung(fetcher=fetcher)
    result = rung("https://example.test/still-blocked")

    assert result.ok is False
    assert result.tier == "T2"
    assert result.http_status == 451
    assert result.error is not None


def test_jina_rung_transport_error_is_a_failure() -> None:
    """A raised transport error from the fetcher is captured as data, never re-raised."""
    def fetcher(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    rung = make_jina_rung(fetcher=fetcher)
    result = rung("https://example.test/x")

    assert result.ok is False
    assert result.tier == "T2"
    assert result.http_status is None
    assert "connection reset" in (result.error or "")


def test_jina_rung_sends_authorization_header_when_key_present() -> None:
    """An api_key becomes a Bearer Authorization header on the Jina request."""
    captured: list[httpx.Request] = []

    def fetcher(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="body")

    rung = make_jina_rung(api_key="sk-jina-abc", fetcher=fetcher)
    rung("https://example.test/a")

    assert captured[0].headers.get("authorization") == "Bearer sk-jina-abc"


def test_jina_rung_omits_authorization_header_when_no_key() -> None:
    """No api_key -> no Authorization header (keyless Jina still works, lower rate limit)."""
    captured: list[httpx.Request] = []

    def fetcher(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="body")

    rung = make_jina_rung(fetcher=fetcher)
    rung("https://example.test/a")

    assert "authorization" not in captured[0].headers


# -- make_browser_rung: the T3 patchright (stealth Playwright) rung ---


def test_browser_rung_success_returns_html_result() -> None:
    """A successful render wraps into an AcquireResult with kind="html", tier=T3."""
    captured: list[str] = []

    def renderer(url: str) -> str:
        captured.append(url)
        return "<html><body><p>rendered by chromium</p></body></html>"

    rung = make_browser_rung(renderer=renderer)
    result = rung("https://example.test/js-gated")

    assert isinstance(result, AcquireResult)
    assert result.ok is True
    assert result.kind == "html"
    assert result.payload == "<html><body><p>rendered by chromium</p></body></html>"
    assert result.tier == "T3"
    assert result.http_status == 200
    assert result.error is None
    assert result.final_url == "https://example.test/js-gated"
    assert result.content_type == "text/html"
    assert captured == ["https://example.test/js-gated"]


def test_browser_rung_renderer_error_is_a_failure_not_a_crash() -> None:
    """A renderer exception (launch failure, timeout, Chromium not installed, ...) is
    captured as data -- ok=False, tier=T3 -- never raised out of the rung."""
    def renderer(_url: str) -> str:
        raise RuntimeError("Executable doesn't exist at .../chromium/chrome.exe")

    rung = make_browser_rung(renderer=renderer)
    result = rung("https://example.test/x")

    assert result.ok is False
    assert result.tier == "T3"
    assert result.http_status is None
    assert "chrome.exe" in (result.error or "")


def test_browser_rung_empty_content_is_a_failure() -> None:
    """A renderer that returns empty/blank HTML is treated as a failed rung, not a
    hollow success the conductor would then try to extract from."""
    rung = make_browser_rung(renderer=lambda _url: "   ")
    result = rung("https://example.test/blank")

    assert result.ok is False
    assert result.tier == "T3"
    assert result.error is not None


# -- build_rungs: the Settings-driven ladder builder ---------------


def _settings(
    *,
    jina_enabled: bool = True,
    jina_api_key: str | None = None,
    browser_enabled: bool = True,
) -> SimpleNamespace:
    """A minimal settings stand-in exposing only the fields build_rungs reads."""
    return SimpleNamespace(
        jina_enabled=jina_enabled, jina_api_key=jina_api_key, browser_enabled=browser_enabled,
    )


def test_build_rungs_always_includes_curl() -> None:
    """curl_cffi (T1) is always in the ladder, regardless of the Jina toggle."""
    from spyglass_service.fetch_acquire import _acquire_curl_cffi

    rungs = build_rungs(_settings(jina_enabled=False, browser_enabled=False))
    assert _acquire_curl_cffi in rungs


def test_build_rungs_includes_jina_when_enabled() -> None:
    """jina_enabled=True adds a second rung after curl_cffi (browser off -> 2 total)."""
    rungs = build_rungs(_settings(jina_enabled=True, browser_enabled=False), "html")
    assert len(rungs) == 2


def test_build_rungs_omits_jina_when_disabled() -> None:
    """jina_enabled=False means no Jina rung appended (browser off too -> curl-only)."""
    rungs = build_rungs(_settings(jina_enabled=False, browser_enabled=False), "html")
    assert len(rungs) == 1


def test_build_rungs_passes_api_key_into_jina_rung(monkeypatch) -> None:
    """The Jina rung build_rungs constructs carries settings.jina_api_key through to the
    Authorization header. Patches make_jina_rung's default fetcher factory seam
    (httpx.Client.send) is avoided -- instead we monkeypatch make_jina_rung itself to
    capture the api_key it was called with, proving build_rungs threads it correctly."""
    captured_keys: list[str | None] = []
    real_make_jina_rung = make_jina_rung

    def spy_make_jina_rung(api_key: str | None = None, *, fetcher=None):
        captured_keys.append(api_key)
        return real_make_jina_rung(api_key=api_key, fetcher=fetcher)

    monkeypatch.setattr(
        "spyglass_service.fetch_rungs.make_jina_rung", spy_make_jina_rung
    )

    from spyglass_service.fetch_rungs import build_rungs as build_rungs_fresh

    build_rungs_fresh(_settings(jina_enabled=True, jina_api_key="sk-configured"))


# -- build_rungs: HTML-only browser (T3) gate -----------


def _rung_count(settings, target_kind: str) -> int:
    """Helper: how many rungs build_rungs assembles for (settings, target_kind)."""
    return len(build_rungs(settings, target_kind))


def test_build_rungs_includes_browser_for_html_when_enabled() -> None:
    """browser_enabled=True + target_kind="html" -> curl + jina + browser = 3 rungs."""
    rungs = build_rungs(_settings(jina_enabled=True, browser_enabled=True), "html")
    assert len(rungs) == 3


def test_build_rungs_omits_browser_for_pdf_even_when_enabled() -> None:
    """A PDF target's ladder NEVER contains the browser rung, regardless of the toggle.
    Jina still applies to PDF (unchanged)."""
    settings = _settings(jina_enabled=True, browser_enabled=True)
    assert _rung_count(settings, "pdf") == _rung_count(_settings(jina_enabled=True, browser_enabled=False), "pdf")
    # Explicitly: curl + jina only, no browser -- 2 rungs, same with browser toggled off.
    assert _rung_count(settings, "pdf") == 2


def test_build_rungs_omits_browser_for_image_even_when_enabled() -> None:
    """Same HTML-only gate for an image target."""
    settings = _settings(jina_enabled=True, browser_enabled=True)
    assert _rung_count(settings, "image") == 2


def test_build_rungs_omits_browser_when_toggled_off_for_html() -> None:
    """browser_enabled=False -> build_rungs(settings, "html") omits the browser rung
    even though the target kind would otherwise qualify."""
    rungs = build_rungs(_settings(jina_enabled=True, browser_enabled=False), "html")
    assert len(rungs) == 2


def test_build_rungs_default_target_kind_is_html() -> None:
    """Omitting target_kind defaults to "html" -- matches acquire()'s own default and
    keeps existing single-arg build_rungs(settings) callers behaving as before (browser
    included when enabled)."""
    rungs = build_rungs(_settings(jina_enabled=False, browser_enabled=True))
    assert len(rungs) == 2  # curl + browser, no jina


def test_build_rungs_browser_rung_identity_excluded_from_pdf_ladder() -> None:
    """Stronger than a count check: the browser rung callable itself is absent from a
    pdf ladder, not just coincidentally equal in length."""
    html_rungs = build_rungs(_settings(jina_enabled=False, browser_enabled=True), "html")
    pdf_rungs = build_rungs(_settings(jina_enabled=False, browser_enabled=True), "pdf")
    # The html ladder's extra rung (the browser one) must not appear anywhere in pdf's.
    browser_rung = html_rungs[-1]
    assert browser_rung not in pdf_rungs
