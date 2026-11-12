"""Tests for the headless-browser request guard in the engine's fetch rungs."""

import sys
import types

import pytest

from spyglass_service import fetch_rungs
from spyglass_service.radar import netguard


class _Route:
    """Records whether a request was aborted or continued."""

    def __init__(self) -> None:
        self.action: str | None = None

    def abort(self) -> None:
        """Mark the request aborted."""
        self.action = "abort"

    def continue_(self) -> None:
        """Mark the request continued."""
        self.action = "continue"


def _decide(url: str, guard=None) -> str | None:
    """What a request guard does with a request to `url` (a fresh guard unless one is given)."""
    route = _Route()
    (guard or fetch_rungs.make_request_guard())(route, types.SimpleNamespace(url=url))
    return route.action


@pytest.mark.parametrize("url", [
    "http://localhost:8080/x",
    "http://LOCALHOST/",
    "https://printer.local/status",
    "http://service.internal/",
    "http://127.0.0.1:7777/api/cards",
    "http://10.1.2.3/",
    "http://192.168.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://100.64.0.1/",
    "file:///C:/Windows/win.ini",
    "ftp://example.org/file",
])
def test_internal_and_unusual_requests_are_aborted(url: str) -> None:
    """Loopback, private, link-local, internal names and non-web schemes never load."""
    assert _decide(url) == "abort"


@pytest.mark.parametrize("url", [
    "https://example.org/page",
    "http://93.184.216.34/",
    "data:text/plain;base64,aGk=",
    "blob:https://example.org/1234",
    "about:blank",
])
def test_public_and_inline_requests_continue(url: str) -> None:
    """Ordinary web addresses and inline resources are allowed."""
    assert _decide(url) == "continue"


def test_a_public_name_resolving_to_a_private_address_is_aborted(monkeypatch) -> None:
    """The guard resolves names, so a rebinding-style host cannot reach the private network."""
    monkeypatch.setattr(netguard, "resolve",
                        lambda host: ["10.0.0.5"] if host == "sneaky.example.net" else ["93.184.216.34"])
    guard = fetch_rungs.make_request_guard()
    assert _decide("https://sneaky.example.net/a.js", guard) == "abort"
    assert _decide("https://fine.example.org/a.js", guard) == "continue"


def test_a_name_that_does_not_resolve_is_aborted(monkeypatch) -> None:
    """is_public_url refuses a name it cannot resolve, so the guard does too."""
    def fail(host: str) -> list[str]:
        """A resolver that cannot find the host."""
        raise OSError("no such host")

    monkeypatch.setattr(netguard, "resolve", fail)
    assert _decide("https://gone.example.net/") == "abort"


def test_each_host_is_resolved_once_per_page(monkeypatch) -> None:
    """Verdicts are cached for the page, so many sub-resources cost one lookup per host."""
    calls: list[str] = []

    def resolver(host: str) -> list[str]:
        """Count lookups."""
        calls.append(host)
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve", resolver)
    guard = fetch_rungs.make_request_guard()
    for path in ("a.js", "b.css", "c.png"):
        assert _decide(f"https://cdn.example.org/{path}", guard) == "continue"
    assert _decide("https://other.example.org/x", guard) == "continue"
    assert calls == ["cdn.example.org", "other.example.org"]
    # A new page gets a new guard; the 60-second lookup cache still answers for the same host,
    # and once that cache is cleared the host is looked up again.
    _decide("https://cdn.example.org/a.js")
    assert calls.count("cdn.example.org") == 1
    netguard.clear_lookup_cache()
    _decide("https://cdn.example.org/a.js")
    assert calls.count("cdn.example.org") == 2


def test_is_internal_host_matches_the_url_check() -> None:
    """The shared helper agrees with is_public_url for names that need no lookup."""
    assert netguard.is_internal_host("localhost") and netguard.is_internal_host("[::1]")
    assert netguard.is_internal_host("box.lan") and not netguard.is_internal_host("example.org")
    assert not netguard.is_public_url("http://box.lan/")


def test_default_renderer_installs_the_guard_before_navigating(monkeypatch) -> None:
    """The real renderer registers the route handler on the page before it opens the URL."""
    events: list[str] = []
    landed = {"url": "https://example.org/"}

    class Page:
        """Fake browser page."""

        @property
        def url(self) -> str:
            """The address the page ended on."""
            return landed["url"]

        def route(self, pattern, handler) -> None:
            """Record the route registration."""
            events.append(f"route:{pattern}:{callable(handler)}")

        def route_web_socket(self, pattern, handler) -> None:
            """Record the WebSocket guard registration."""
            events.append(f"websocket:{pattern('ws://x/')}:{callable(handler)}")

        def goto(self, url, timeout=0) -> None:
            """Record the navigation."""
            events.append("goto")

        def content(self) -> str:
            """Return canned markup."""
            return "<html>ok</html>"

    class Context:
        """Fake browser context."""

        def new_page(self) -> Page:
            """Open a fake page."""
            return Page()

    class Browser:
        """Fake browser."""

        def new_context(self, **options) -> "Context":
            """Open a fake context; service workers must be blocked."""
            events.append(f"context:service_workers={options.get('service_workers')}")
            return Context()

        def close(self) -> None:
            """Record the close."""
            events.append("close")

    launched: list[list[str]] = []

    class Playwright:
        """Fake playwright driver."""

        chromium = types.SimpleNamespace(
            launch=lambda headless=True, args=(): launched.append(list(args)) or Browser())

    class Manager:
        """Fake context manager for sync_playwright()."""

        def __enter__(self) -> Playwright:
            return Playwright()

        def __exit__(self, *exc) -> None:
            return None

    module = types.ModuleType("patchright.sync_api")
    module.sync_playwright = lambda: Manager()
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    monkeypatch.setitem(sys.modules, "patchright.sync_api", module)
    rung = fetch_rungs.make_browser_rung()
    result = rung("https://example.org/")
    # Launched with local-network checks on and the page's host pinned to its checked address.
    assert any(a.startswith("--enable-features=LocalNetworkAccessChecks") for a in launched[0])
    assert "--host-resolver-rules=MAP example.org 93.184.216.34" in launched[0]
    assert result.ok and events == [
        "context:service_workers=block", "route:**/*:True", "websocket:True:True", "goto", "close"]
    assert events[-1] == "close"

    # A page that ends on a private address (a redirect the guard missed) yields a failed result.
    events.clear()
    landed["url"] = "http://192.168.1.1/admin"
    failed = rung("https://example.org/")
    assert not failed.ok and "non-public" in failed.error


class _Socket:
    """Records whether a WebSocket was connected through or closed."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.action: str | None = None

    def connect_to_server(self) -> None:
        """Mark the connection allowed."""
        self.action = "connect"

    def close(self, code=None, reason=None) -> None:
        """Mark the connection refused."""
        self.action = "close"


@pytest.mark.parametrize(("url", "expected"), [
    ("ws://127.0.0.1:7778/socket", "close"),
    ("ws://localhost:3000/", "close"),
    ("wss://10.0.0.5/live", "close"),
    ("ws://printer.local/", "close"),
    ("wss://example.org/live", "connect"),
])
def test_websockets_to_non_public_hosts_are_closed(url: str, expected: str) -> None:
    """A page cannot open a WebSocket to this computer or a private network."""
    socket = _Socket(url)
    fetch_rungs.make_websocket_guard()(socket)
    assert socket.action == expected


def test_the_browser_page_helper_blocks_service_workers_and_guards_sockets() -> None:
    """Service workers are blocked (their fetches bypass the route guard) and both guards are set."""
    seen: dict = {}

    class Page:
        """Fake page."""

        def route(self, pattern, handler) -> None:
            seen["route"] = pattern

        def route_web_socket(self, pattern, handler) -> None:
            seen["websocket"] = pattern("ws://any.example/")

    class Context:
        """Fake context."""

        def new_page(self) -> Page:
            return Page()

    class Browser:
        """Fake browser."""

        def new_context(self, **options) -> Context:
            seen["options"] = options
            return Context()

    fetch_rungs.open_guarded_page(Browser())
    # The context also starts empty with nothing granted (checked in test_page_fetch_guard.py).
    assert seen["options"]["service_workers"] == "block"
    assert {k: seen[k] for k in ("route", "websocket")} == {"route": "**/*", "websocket": True}
