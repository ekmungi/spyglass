"""Connections are pinned to the addresses the address check approved (all with fakes)."""

import types

import httpcore
import httpx
import pytest

from spyglass_service import fetch_rungs
from spyglass_service.radar import netguard, netpin


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty lookup cache and no real waiting in every test."""
    netguard.clear_lookup_cache()
    monkeypatch.setattr(netguard, "_sleep", lambda _s: None)


def _resolve_to(monkeypatch, *addresses: str) -> None:
    """Make every lookup answer `addresses`."""
    monkeypatch.setattr(netguard, "resolve", lambda host: list(addresses))


def test_checked_addresses_are_the_public_answers(monkeypatch) -> None:
    """A public name gives its addresses; a literal gives itself."""
    _resolve_to(monkeypatch, "93.184.216.34", "2606:2800:220:1::1")
    assert netguard.checked_addresses("a.example") == ["93.184.216.34", "2606:2800:220:1::1"]
    assert netguard.checked_addresses("93.184.216.34") == ["93.184.216.34"]


@pytest.mark.parametrize("host", ["10.0.0.1", "localhost", "printer.local"])
def test_checked_addresses_refuse_private_hosts(host: str) -> None:
    """Private literals and internal names are refused."""
    with pytest.raises(netguard.UnpinnableHost):
        netguard.checked_addresses(host)


def test_checked_addresses_refuse_a_private_answer_and_no_answer(monkeypatch) -> None:
    """A name answering privately, or not at all, is refused."""
    _resolve_to(monkeypatch, "192.168.1.9")
    with pytest.raises(netguard.UnpinnableHost):
        netguard.checked_addresses("a.example")

    def fail(host: str) -> list[str]:
        raise OSError("no answer")

    netguard.clear_lookup_cache()
    monkeypatch.setattr(netguard, "resolve", fail)
    with pytest.raises(netguard.UnpinnableHost):
        netguard.checked_addresses("b.example")


def test_curl_resolve_entry_pins_host_and_port(monkeypatch) -> None:
    """curl gets host:port:addresses, IPv6 in brackets; a literal needs no entry."""
    _resolve_to(monkeypatch, "93.184.216.34", "2606:2800:220:1::1")
    assert netpin.curl_resolve("https://a.example/x") == [
        "a.example:443:93.184.216.34,[2606:2800:220:1::1]"]
    assert netpin.curl_resolve("http://a.example:8080/x") == [
        "a.example:8080:93.184.216.34,[2606:2800:220:1::1]"]
    assert netpin.curl_resolve("https://93.184.216.34/x") is None


def test_the_guarded_curl_rung_pins_each_hop(monkeypatch) -> None:
    """Every curl request carries the resolve entry for the address that was checked."""
    from curl_cffi import CurlOpt
    from curl_cffi import requests as curl_requests

    _resolve_to(monkeypatch, "93.184.216.34")
    seen: list[dict] = []

    def fake_get(url: str, **kwargs):
        seen.append(kwargs)
        return types.SimpleNamespace(status_code=200, headers={"content-type": "text/html"},
                                     content=b"<p>x</p>", url=url, encoding="utf-8")

    monkeypatch.setattr(curl_requests, "get", fake_get)
    result = fetch_rungs.make_guarded_curl_rung()("https://a.example/page")
    assert result.ok
    assert seen[0]["curl_options"] == {CurlOpt.RESOLVE: ["a.example:443:93.184.216.34"]}


def test_the_guarded_curl_rung_reports_an_unresolved_name_as_passing(monkeypatch) -> None:
    """A lookup failure is "could not be reached", not a refused address."""
    def fail(host: str) -> list[str]:
        raise OSError("no answer")

    monkeypatch.setattr(netguard, "resolve", fail)
    result = fetch_rungs.make_guarded_curl_rung()("https://a.example/page")
    assert not result.ok and result.error == netguard.UNREACHABLE


def test_chromium_launch_arguments_turn_on_local_network_checks_and_pin_the_page(monkeypatch) -> None:
    """The browser blocks public-to-private requests and resolves the page's host as checked."""
    _resolve_to(monkeypatch, "93.184.216.34")
    args = netpin.chromium_args("https://a.example/story")
    assert "--enable-features=LocalNetworkAccessChecks,LocalNetworkAccessChecksWebSockets" in args
    assert "--host-resolver-rules=MAP a.example 93.184.216.34" in args
    assert not any(a.startswith("--host-resolver-rules") for a in netpin.chromium_args("https://93.184.216.34/"))


def test_the_pinned_backend_connects_to_the_checked_address(monkeypatch) -> None:
    """httpx connects to the address the check approved while keeping the name for TLS."""
    _resolve_to(monkeypatch, "93.184.216.34")
    dialled: list[str] = []

    def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        dialled.append(host)
        raise httpcore.ConnectError("no network in tests")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    with netguard.page_client() as client:
        assert netpin.is_pinned(client)
        with pytest.raises(httpx.ConnectError):
            client.get("https://a.example/")
    assert dialled == ["93.184.216.34"]


def test_the_pinned_backend_refuses_when_the_answer_turns_private(monkeypatch) -> None:
    """A name that answers privately at connection time is never dialled."""
    dialled: list[str] = []
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp",
                        lambda self, host, port, **kw: dialled.append(host))
    _resolve_to(monkeypatch, "10.0.0.7")
    with pytest.raises(httpcore.ConnectError):
        netpin.PinnedBackend().connect_tcp("a.example", 443)
    assert dialled == []


def test_the_pinned_backend_tries_the_next_checked_address(monkeypatch) -> None:
    """When the first approved address does not answer, the next approved one is tried."""
    _resolve_to(monkeypatch, "2606:2800:220:1::1", "93.184.216.34")
    dialled: list[str] = []

    def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        dialled.append(host)
        if ":" in host:
            raise httpcore.ConnectError("no IPv6 route")
        return "stream"

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    assert netpin.PinnedBackend().connect_tcp("a.example", 443) == "stream"
    assert dialled == ["2606:2800:220:1::1", "93.184.216.34"]
