"""The structural guard on outgoing reader requests: every request and redirect hop is checked.

These are the regression tests for the redirect-guard bypasses: a server that answers the real
request differently from the pre-flight, a pre-flight that fails or times out, and a chain longer
than the pre-flight walks.
"""

from types import SimpleNamespace

import httpx
import pytest

from spyglass_service import fetch_rungs
from spyglass_service.fetch_types import AcquireResult
from spyglass_service.radar import netguard
from spyglass_service.radar.reader import http as http_mod
from spyglass_service.radar.reader.redirects import MAX_HOPS, resolve_redirects

SETTINGS = SimpleNamespace(jina_enabled=False, browser_enabled=False, jina_api_key=None)


def guarded(handler) -> httpx.Client:
    """A redirect-following client over a canned transport, wrapped in the guard under test."""
    return netguard.guard_client(
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def redirect(location: str, status: int = 302) -> httpx.Response:
    """A redirect response."""
    return httpx.Response(status, headers={"location": location})


@pytest.fixture
def no_real_curl(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the curl_cffi rung (a real network call) with a recorder that always fails."""
    calls: list[str] = []

    def fake(url: str, **kwargs) -> AcquireResult:
        """Record the address and fail."""
        calls.append(url)
        return AcquireResult(payload=b"", kind="bytes", final_url=url, content_type="", tier="T1",
                             http_status=None, error="no network in tests", ok=False)

    monkeypatch.setattr(fetch_rungs, "_acquire_curl_cffi", fake)
    return calls


def run_fetcher(monkeypatch: pytest.MonkeyPatch, handler, start: str = "https://evil.example/a"):
    """Run the default fetcher against `handler`; return (requests seen, page)."""
    seen: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        """Record the request, then let the scenario answer it."""
        seen.append(str(request.url))
        return handler(request, len(seen))

    monkeypatch.setattr(http_mod, "build_client", lambda: guarded(wrapped))
    page = http_mod.make_fetcher(SETTINGS, None)(start)
    return seen, page


# ---- the guard itself ----------------------------------------------------------------------

def test_a_request_to_a_private_address_is_refused_before_it_is_sent() -> None:
    seen: list[str] = []
    client = guarded(lambda request: seen.append(str(request.url)) or httpx.Response(200))
    with pytest.raises(netguard.BlockedAddress):
        client.get("http://127.0.0.1:7778/api/radar/collect")
    assert seen == []
    client.close()


def test_blocked_address_is_an_httpx_error_and_marks_the_client() -> None:
    client = guarded(lambda request: httpx.Response(200))
    assert not netguard.was_blocked(client)
    with pytest.raises(httpx.HTTPError):
        client.get("http://10.0.0.1/admin")
    assert netguard.was_blocked(client)
    client.close()


def test_every_redirect_hop_is_checked_not_only_the_first_request() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return redirect("http://localhost:7778/api")

    client = guarded(handler)
    with pytest.raises(netguard.BlockedAddress):
        client.get("https://evil.example/a")
    assert seen == ["https://evil.example/a"]
    client.close()


def test_a_name_that_resolves_to_a_private_address_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(netguard, "resolve",
                        lambda host: ["10.1.2.3"] if host == "sneaky.example" else ["93.184.216.34"])
    client = guarded(lambda request: httpx.Response(200))
    with pytest.raises(netguard.BlockedAddress):
        client.get("https://sneaky.example/x")
    client.close()


def test_a_long_redirect_chain_fails_instead_of_running_on() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return redirect(f"/{int(request.url.path.strip('/') or 0) + 1}")

    client = guarded(handler)
    with pytest.raises(httpx.TooManyRedirects):
        client.get("https://evil.example/0")
    client.close()


def test_a_public_chain_still_works() -> None:
    client = guarded(lambda request: redirect("https://b.example/x") if request.url.host == "a.example"
                     else httpx.Response(200, text="done"))
    assert client.get("https://a.example/").text == "done"
    client.close()


def test_the_readers_default_client_carries_the_guard() -> None:
    client = http_mod.build_client()
    try:
        with pytest.raises(netguard.BlockedAddress):
            client.get("http://127.0.0.1:7778/")  # refused by the hook before any connection
    finally:
        client.close()


# ---- the three reported bypasses, through the real fetcher -----------------------------------

def test_a_server_that_answers_the_real_request_differently_is_still_stopped(monkeypatch, no_real_curl) -> None:
    def handler(request: httpx.Request, n: int) -> httpx.Response:
        if request.url.host == "127.0.0.1":
            return httpx.Response(200, text="internal")
        if n == 1:  # the pre-flight sees a harmless page
            return httpx.Response(200, text="ok")
        return redirect("http://127.0.0.1:7778/api/radar/collect")

    seen, page = run_fetcher(monkeypatch, handler)
    assert not any("127.0.0.1" in url for url in seen)
    assert not page.ok and "cannot be fetched" in page.error
    assert no_real_curl == []  # a refused hop ends the ladder: no later rung tries the address


def test_a_failing_pre_flight_does_not_fall_through_to_the_ladder(monkeypatch, no_real_curl) -> None:
    def handler(request: httpx.Request, n: int) -> httpx.Response:
        if request.url.host in ("127.0.0.1", "10.0.0.1"):
            return httpx.Response(200, text="internal")
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return redirect("http://10.0.0.1/admin")

    seen, page = run_fetcher(monkeypatch, handler)
    assert seen == ["https://evil.example/a"]  # nothing after the failed pre-flight
    assert not page.ok and no_real_curl == []


def test_a_chain_longer_than_the_pre_flight_walks_is_refused(monkeypatch, no_real_curl) -> None:
    def handler(request: httpx.Request, n: int) -> httpx.Response:
        if request.url.host in ("127.0.0.1", "10.0.0.1"):
            return httpx.Response(200, text="internal")
        step = int(request.url.path.strip("/") or 0)
        target = f"https://evil.example/{step + 1}" if step < 8 else "http://10.0.0.1/admin"
        return redirect(target)

    seen, page = run_fetcher(monkeypatch, handler, start="https://evil.example/0")
    assert not any("10.0.0.1" in url for url in seen)
    assert not page.ok


def test_the_direct_request_path_with_headers_is_guarded_too(monkeypatch) -> None:
    def handler(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return httpx.Response(200)
        return redirect("http://169.254.169.254/latest/meta-data/")

    monkeypatch.setattr(http_mod, "build_client", lambda: guarded(lambda r: handler(r, 2)))
    monkeypatch.setattr(http_mod, "resolve_redirects",
                        lambda client, url: SimpleNamespace(url=url, blocked=False))
    page = http_mod.make_fetcher(SETTINGS, None)("https://api.example/x", headers={"Accept": "x"})
    assert not page.ok and "cannot be fetched" in page.error


# ---- the pre-flight now fails closed ---------------------------------------------------------

def test_the_pre_flight_treats_a_timeout_as_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    assert resolve_redirects(client, "https://example.org/a").blocked
    client.close()


def test_the_pre_flight_treats_the_hop_limit_as_blocked() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: redirect(f"/{int(request.url.path.strip('/') or 0) + 1}")),
        follow_redirects=True)
    assert resolve_redirects(client, "https://example.org/0").blocked
    client.close()


def test_the_pre_flight_allows_exactly_the_hop_limit_in_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        step = int(request.url.path.strip("/") or 0)
        return redirect(f"/{step + 1}") if step < MAX_HOPS else httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    outcome = resolve_redirects(client, "https://example.org/0")
    assert not outcome.blocked and outcome.url == f"https://example.org/{MAX_HOPS}"
    client.close()


# ---- the curl_cffi rung ------------------------------------------------------------------------

class FakeCurlResponse:
    """Just enough of a curl_cffi response for the rung."""

    def __init__(self, status: int, headers: dict, url: str) -> None:
        self.status_code, self.headers, self.url = status, headers, url
        self.content, self.encoding = b"body", "utf-8"


def install_fake_curl(monkeypatch, responder):
    """Replace `curl_cffi.requests.get`; return the list of (url, kwargs) it received."""
    from curl_cffi import requests as curl_requests

    calls: list[tuple[str, dict]] = []

    def fake_get(url: str, **kwargs):
        """Record the call and answer from the scenario."""
        calls.append((url, kwargs))
        return responder(url, kwargs)

    monkeypatch.setattr(curl_requests, "get", fake_get)
    return calls


def test_the_curl_rung_follows_redirects_itself_by_default(monkeypatch) -> None:
    from spyglass_service.fetch_acquire import _acquire_curl_cffi

    calls = install_fake_curl(monkeypatch, lambda url, kw: FakeCurlResponse(200, {}, url))
    assert _acquire_curl_cffi("https://a.example/").ok
    assert "allow_redirects" not in calls[0][1]  # existing callers see no change


def test_the_curl_rung_can_be_told_not_to_follow_and_reports_the_location(monkeypatch) -> None:
    from spyglass_service.fetch_acquire import _acquire_curl_cffi

    calls = install_fake_curl(
        monkeypatch, lambda url, kw: FakeCurlResponse(302, {"location": "/next"}, url))
    result = _acquire_curl_cffi("https://a.example/start", follow_redirects=False)
    assert calls[0][1]["allow_redirects"] is False
    assert not result.ok and result.http_status == 302
    assert result.final_url == "https://a.example/next"


def test_the_guarded_curl_rung_checks_every_hop_and_never_requests_a_private_one(monkeypatch) -> None:
    def respond(url: str, kw: dict):
        if url == "https://a.example/start":
            return FakeCurlResponse(302, {"location": "https://b.example/mid"}, url)
        if url == "https://b.example/mid":
            return FakeCurlResponse(301, {"location": "http://192.168.0.1/router"}, url)
        return FakeCurlResponse(200, {}, url)

    calls = install_fake_curl(monkeypatch, respond)
    result = fetch_rungs.make_guarded_curl_rung()("https://a.example/start")
    assert [url for url, _ in calls] == ["https://a.example/start", "https://b.example/mid"]
    assert all(kw.get("allow_redirects") is False for _, kw in calls)
    assert not result.ok and "cannot be fetched" in (result.error or "")


def test_the_guarded_curl_rung_returns_the_page_at_the_end_of_a_public_chain(monkeypatch) -> None:
    def respond(url: str, kw: dict):
        if url.endswith("/start"):
            return FakeCurlResponse(302, {"location": "https://b.example/page"}, url)
        return FakeCurlResponse(200, {"content-type": "text/html"}, url)

    install_fake_curl(monkeypatch, respond)
    result = fetch_rungs.make_guarded_curl_rung()("https://a.example/start")
    assert result.ok and result.final_url == "https://b.example/page" and result.tier == "T1"


def test_the_guarded_curl_rung_stops_at_the_hop_limit(monkeypatch) -> None:
    calls = install_fake_curl(
        monkeypatch,
        lambda url, kw: FakeCurlResponse(302, {"location": f"/{len(url)}x"}, url))
    result = fetch_rungs.make_guarded_curl_rung(max_hops=3)("https://a.example/0")
    assert not result.ok and len(calls) <= 4


def test_build_rungs_uses_the_guarded_curl_rung_unless_told_not_to() -> None:
    plain = fetch_rungs.build_rungs(SETTINGS, "html", guarded=False)
    assert plain[0] is fetch_rungs._acquire_curl_cffi
    guarded_rungs = fetch_rungs.build_rungs(SETTINGS, "html")
    assert guarded_rungs[0] is not fetch_rungs._acquire_curl_cffi
    assert getattr(guarded_rungs[0], "tier", None) == "T1"

