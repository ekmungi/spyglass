"""Tests for the by-hand redirect pre-flight that runs before the fetch ladder."""

import httpx
import pytest

from spyglass_service.config import Settings
from spyglass_service.fetch_types import AcquireResult
from spyglass_service.radar.reader import http as http_mod
from spyglass_service.radar.reader.redirects import resolve_redirects


def _client(handler) -> httpx.Client:
    """A client that follows redirects by default (like the engine's) over a canned transport."""
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _redirect(location: str, status: int = 302) -> httpx.Response:
    """A redirect response."""
    return httpx.Response(status, headers={"location": location})


def test_a_page_without_redirects_is_returned_as_is() -> None:
    """No redirect means the original address comes back, not blocked."""
    client = _client(lambda request: httpx.Response(200, text="hello"))
    outcome = resolve_redirects(client, "https://example.org/a")
    assert outcome.url == "https://example.org/a" and not outcome.blocked
    client.close()


def test_a_public_chain_is_followed_by_hand_including_relative_locations() -> None:
    """Each hop is requested in turn and the final address is returned."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Redirect /a to /b to an outside host."""
        seen.append(str(request.url))
        if request.url.path == "/a":
            return _redirect("/b")
        if request.url.path == "/b":
            return _redirect("https://other.example.net/c", 301)
        return httpx.Response(200, text="end")

    client = _client(handler)
    outcome = resolve_redirects(client, "https://example.org/a")
    assert outcome.url == "https://other.example.net/c" and not outcome.blocked
    assert seen == ["https://example.org/a", "https://example.org/b", "https://other.example.net/c"]
    client.close()


def test_a_redirect_to_a_private_address_is_blocked_and_never_requested() -> None:
    """A hop into a private range is refused before any request is sent to it."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Always redirect to the cloud metadata address."""
        seen.append(str(request.url))
        return _redirect("http://169.254.169.254/latest/meta-data/")

    client = _client(handler)
    outcome = resolve_redirects(client, "https://example.org/a")
    assert outcome.blocked
    assert seen == ["https://example.org/a"]
    client.close()


def test_a_redirect_to_a_name_that_resolves_privately_is_blocked(monkeypatch) -> None:
    """A host name whose lookup returns a private address is refused too."""
    monkeypatch.setattr("spyglass_service.radar.netguard.resolve",
                        lambda host: ["10.0.0.7"] if host == "sneaky.example.net" else ["93.184.216.34"])
    client = _client(lambda request: _redirect("https://sneaky.example.net/x"))
    assert resolve_redirects(client, "https://example.org/a").blocked
    client.close()


def test_a_chain_longer_than_the_hop_limit_is_refused() -> None:
    """More than MAX_HOPS redirects is a refusal, not a hand-over to the ladder."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Redirect /n to /n+1 forever."""
        number = int(request.url.path.strip("/") or 0)
        return _redirect(f"/{number + 1}")

    client = _client(handler)
    assert resolve_redirects(client, "https://example.org/0").blocked
    client.close()


def test_a_network_error_refuses_the_link() -> None:
    """A connection error part-way is a refusal: the ladder must not run on an unchecked chain."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Redirect once, then fail to connect."""
        if request.url.path == "/a":
            return _redirect("/b")
        raise httpx.ConnectError("down")

    client = _client(handler)
    assert resolve_redirects(client, "https://example.org/a").blocked
    client.close()


def test_a_redirect_without_a_location_ends_the_pre_flight() -> None:
    """A 302 with no Location header is treated as the end of the chain."""
    client = _client(lambda request: httpx.Response(302))
    assert resolve_redirects(client, "https://example.org/a").url == "https://example.org/a"
    client.close()


def test_the_default_fetcher_refuses_a_redirect_into_a_private_network(monkeypatch) -> None:
    """A blocked chain never reaches the ladder and comes back as a failed page."""
    client = _client(lambda request: _redirect("http://127.0.0.1:9999/secret"))
    monkeypatch.setattr(http_mod, "build_client", lambda: client)
    monkeypatch.setattr(http_mod, "acquire",
                        lambda *a, **k: pytest.fail("the ladder must not run for a blocked redirect"))
    page = http_mod.make_fetcher(Settings())("https://example.org/a")
    assert not page.ok and "cannot be fetched" in page.error


def test_the_default_fetcher_hands_the_validated_address_to_the_ladder(monkeypatch) -> None:
    """The ladder starts from the end of the chain the pre-flight walked."""
    client = _client(lambda request: _redirect("https://final.example.net/p")
                     if request.url.host == "example.org" else httpx.Response(200))
    monkeypatch.setattr(http_mod, "build_client", lambda: client)
    seen: dict = {}

    def fake_acquire(url, **kwargs):
        """Record the address the ladder was given."""
        seen["url"] = url
        return AcquireResult(payload=b"<p>hi</p>", kind="bytes", final_url=url, content_type="text/html",
                             tier="T0", http_status=200, error=None, ok=True, encoding="utf-8")

    monkeypatch.setattr(http_mod, "acquire", fake_acquire)
    monkeypatch.setattr(http_mod, "build_rungs", lambda settings, kind, **kw: ())
    page = http_mod.make_fetcher(Settings())("https://example.org/a")
    assert page.ok and seen["url"] == "https://final.example.net/p"
