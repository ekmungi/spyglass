"""Page fetching carries nothing personal and only reads: the guarded client and the browser."""

import getpass
import socket
import types
from pathlib import Path

import httpx
import pytest

from spyglass_service import fetch_rungs
from spyglass_service.radar import netguard
from spyglass_service.radar.netguard import PAGE_USER_AGENT, RefusedMethod
from spyglass_service.radar.sources import _common


def _guarded(handler) -> httpx.Client:
    """A guarded client whose requests go to `handler`."""
    return netguard.guard_client(httpx.Client(transport=httpx.MockTransport(handler),
                                              follow_redirects=True))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_a_guarded_client_refuses_every_method_but_get_and_head(method: str) -> None:
    """A write request is refused before it is sent: nothing reaches the server."""
    sent: list[str] = []
    with _guarded(lambda r: sent.append(r.method) or httpx.Response(200)) as client:
        with pytest.raises(RefusedMethod):
            client.request(method, "https://example.org/form", data={"q": "x"})
    assert sent == []


def test_get_and_head_go_through() -> None:
    """Reading is allowed."""
    sent: list[str] = []
    with _guarded(lambda r: sent.append(r.method) or httpx.Response(200)) as client:
        client.get("https://example.org/a")
        client.head("https://example.org/a")
    assert sent == ["GET", "HEAD"]


def test_personal_headers_are_stripped_and_the_agent_is_fixed() -> None:
    """Cookie, Authorization and Proxy-Authorization never leave; the agent is the generic one."""
    seen: list[httpx.Headers] = []
    with _guarded(lambda r: seen.append(r.headers) or httpx.Response(200)) as client:
        client.get("https://example.org/a", headers={
            "Cookie": "session=abc", "Authorization": "token secret",
            "Proxy-Authorization": "Basic x", "User-Agent": "reader on laptop-of-someone"})
    headers = seen[0]
    for name in ("cookie", "authorization", "proxy-authorization"):
        assert name not in headers
    assert headers["user-agent"] == PAGE_USER_AGENT


def test_cookies_set_by_a_site_are_never_sent_back() -> None:
    """A Set-Cookie answer is not stored: the next request and the redirect hop carry no cookie."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/next", "set-cookie": "id=track1; Path=/"})
        return httpx.Response(200, headers={"set-cookie": "id=track2; Path=/"})

    with _guarded(handler) as client:
        client.get("https://example.org/start")
        client.get("https://example.org/again")
    assert [r.url.path for r in seen] == ["/start", "/next", "/again"]
    assert all("cookie" not in r.headers for r in seen)


def test_page_client_is_guarded() -> None:
    """The factory's client refuses private addresses and writes."""
    with netguard.page_client() as client:
        with pytest.raises(netguard.BlockedAddress):
            client.get("http://127.0.0.1:7778/api/radar/items")
        with pytest.raises(RefusedMethod):
            client.post("https://example.org/form")


def test_the_page_agent_names_no_person_machine_or_path() -> None:
    """The generic agent carries no user name, machine name, e-mail address or file path."""
    home = str(Path.home())
    for marker in (getpass.getuser(), socket.gethostname(), home, home.replace("\\", "/")):
        assert marker.lower() not in PAGE_USER_AGENT.lower()
    assert "@" not in PAGE_USER_AGENT and "\\" not in PAGE_USER_AGENT


def test_collector_requests_use_the_guarded_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collectors' GET helper follows a redirect only to a public address, with no cookie."""
    seen: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://192.168.1.1/admin"}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    with pytest.raises(netguard.BlockedAddress):
        _common.http_get_bytes("https://hn.algolia.com/api/v1/search", {"query": "x"})
    assert [r.url.host for r in seen] == ["hn.algolia.com"]
    assert seen[0].headers["user-agent"] == PAGE_USER_AGENT


class _Route:
    """Records whether the browser guard aborted or continued a request."""

    def __init__(self) -> None:
        self.action: str | None = None

    def abort(self) -> None:
        """Mark aborted."""
        self.action = "abort"

    def continue_(self) -> None:
        """Mark continued."""
        self.action = "continue"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_the_browser_aborts_every_request_that_is_not_a_read(method: str) -> None:
    """A page's form post, beacon or XHR write to a public site is aborted."""
    route = _Route()
    fetch_rungs.make_request_guard()(route, types.SimpleNamespace(url="https://example.org/x",
                                                                  method=method))
    assert route.action == "abort"


def test_the_browser_lets_reads_of_public_pages_through() -> None:
    """GET and HEAD to a public site continue."""
    for method in ("GET", "HEAD"):
        route = _Route()
        fetch_rungs.make_request_guard()(route, types.SimpleNamespace(url="https://example.org/",
                                                                      method=method))
        assert route.action == "continue"


def test_each_browser_page_gets_a_fresh_context_with_nothing_granted() -> None:
    """Fresh context, no stored state, no permissions, no downloads, no machine locale or zone."""
    calls: dict = {}

    class Page:
        """A page that accepts the guard registrations."""

        def route(self, pattern, handler) -> None:
            """Accept the request guard."""

        def route_web_socket(self, pattern, handler) -> None:
            """Accept the socket guard."""

    class Context:
        """A context that hands out one page."""

        def new_page(self) -> Page:
            """A new page."""
            return Page()

    class Browser:
        """Records the options of the context it creates."""

        def new_context(self, **options) -> Context:
            """Remember the options."""
            calls.update(options)
            return Context()

    fetch_rungs.open_guarded_page(Browser())
    assert calls["service_workers"] == "block"
    assert calls["permissions"] == []
    assert calls["accept_downloads"] is False
    assert calls["storage_state"] is None
    assert calls["locale"] == "en-US" and calls["timezone_id"] == "UTC"
    assert "geolocation" not in calls and "http_credentials" not in calls
