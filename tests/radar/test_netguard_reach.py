"""Three outcomes for an address check (public, not public, could not be resolved), the lookup
retry, the short lookup cache, and how the reader reports a lookup that failed."""

import threading
import time

import httpx
import pytest

from spyglass_service.radar import netguard
from spyglass_service.radar.netguard import Reach, check_url
from spyglass_service.radar.reader import http as reader_http


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Start every test with an empty lookup cache and no real waiting."""
    netguard.clear_lookup_cache()
    slept: list[float] = []
    monkeypatch.setattr(netguard, "_sleep", slept.append)
    return slept


def _counting(answers: list) -> tuple[list[str], callable]:
    """A resolver that returns (or raises) the given answers in order and records each call."""
    calls: list[str] = []

    def resolver(host: str) -> list[str]:
        calls.append(host)
        answer = answers[min(len(calls), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return calls, resolver


def test_three_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public, not public (private answer or private literal) and could not be resolved."""
    monkeypatch.setattr(netguard, "resolve", lambda host: ["93.184.216.34"])
    assert check_url("https://example.org/a") is Reach.PUBLIC
    assert check_url("http://10.0.0.1/") is Reach.NOT_PUBLIC
    assert check_url("file:///etc/passwd") is Reach.NOT_PUBLIC
    monkeypatch.setattr(netguard, "resolve", lambda host: ["192.168.1.4"])
    assert check_url("https://intranet.example/") is Reach.NOT_PUBLIC

    def fail(host: str) -> list[str]:
        raise OSError("temporary failure in name resolution")

    monkeypatch.setattr(netguard, "resolve", fail)
    assert check_url("https://flaky.example/") is Reach.UNRESOLVED
    assert netguard.is_public_url("https://flaky.example/") is False


def test_a_failed_lookup_is_retried_once_after_a_short_pause(monkeypatch, _fresh_cache) -> None:
    """One failure then an answer counts as public; the retry waits 300 ms."""
    calls, resolver = _counting([OSError("busy"), ["93.184.216.34"]])
    monkeypatch.setattr(netguard, "resolve", resolver)
    assert check_url("https://example.org/") is Reach.PUBLIC
    assert calls == ["example.org", "example.org"]
    assert _fresh_cache == [0.3]


def test_two_failed_lookups_mean_could_not_be_resolved(monkeypatch) -> None:
    """The lookup is tried exactly twice before giving up."""
    calls, resolver = _counting([OSError("busy"), OSError("still busy")])
    monkeypatch.setattr(netguard, "resolve", resolver)
    assert check_url("https://example.org/") is Reach.UNRESOLVED
    assert len(calls) == 2


def test_successful_lookups_are_cached_for_a_minute(monkeypatch) -> None:
    """A second check within 60 seconds reuses the answer; after that it looks up again."""
    clock = [1000.0]
    monkeypatch.setattr(netguard, "_now", lambda: clock[0])
    calls, resolver = _counting([["93.184.216.34"]])
    monkeypatch.setattr(netguard, "resolve", resolver)
    check_url("https://example.org/a")
    check_url("https://example.org/b")
    assert len(calls) == 1
    clock[0] += 61
    check_url("https://example.org/c")
    assert len(calls) == 2


def test_failures_are_not_cached(monkeypatch) -> None:
    """A lookup that failed is tried again on the next check."""
    calls, resolver = _counting([OSError("x"), OSError("x"), ["93.184.216.34"]])
    monkeypatch.setattr(netguard, "resolve", resolver)
    assert check_url("https://example.org/") is Reach.UNRESOLVED
    assert check_url("https://example.org/") is Reach.PUBLIC
    assert len(calls) == 3


def test_parallel_checks_of_one_host_share_a_single_lookup(monkeypatch) -> None:
    """Eight threads checking the same host at once cause one lookup."""
    calls: list[str] = []
    lock = threading.Lock()

    def slow(host: str) -> list[str]:
        with lock:
            calls.append(host)
        time.sleep(0.05)
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve", slow)
    results: list[Reach] = []
    threads = [threading.Thread(target=lambda: results.append(check_url("https://example.org/")))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [Reach.PUBLIC] * 8
    assert calls == ["example.org"]


def test_a_custom_resolver_is_never_cached(monkeypatch) -> None:
    """A pinned resolver (the capture path) decides every time, and does not fill the cache."""
    calls, resolver = _counting([["93.184.216.34"]])
    check_url("https://example.org/", resolver=resolver)
    check_url("https://example.org/", resolver=resolver)
    assert len(calls) == 2


def test_the_guarded_client_reports_an_unresolved_name_as_a_connection_failure(monkeypatch) -> None:
    """An unresolved name raises a network error and does not mark the client as refused."""
    def fail(host: str) -> list[str]:
        raise OSError("no answer")

    monkeypatch.setattr(netguard, "resolve", fail)
    client = netguard.guard_client(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200))))
    with pytest.raises(netguard.UnresolvedAddress) as raised:
        client.get("https://flaky.example/")
    client.close()
    assert isinstance(raised.value, httpx.ConnectError)
    assert netguard.was_blocked(client) is False


def test_the_reader_reports_an_unresolved_name_as_transient(monkeypatch, tmp_path) -> None:
    """The reader says the site could not be reached and marks the failure as passing."""
    def fail(host: str) -> list[str]:
        raise OSError("no answer")

    monkeypatch.setattr(netguard, "resolve", fail)
    from spyglass_service.config import Settings

    fetch = reader_http.make_fetcher(Settings(_env_file=None, data_dir=tmp_path))
    page = fetch("https://flaky.example/story")
    assert page.ok is False and page.transient is True
    assert page.error == reader_http.UNREACHABLE


def test_the_reader_still_reports_a_private_address_as_refused(tmp_path) -> None:
    """A private address is a lasting refusal, not a transient failure."""
    from spyglass_service.config import Settings

    fetch = reader_http.make_fetcher(Settings(_env_file=None, data_dir=tmp_path))
    page = fetch("http://127.0.0.1:7778/api/radar/items")
    assert page.ok is False and page.transient is False
    assert page.error == "This address cannot be fetched."


def test_a_redirect_walk_that_times_out_is_transient() -> None:
    """A network failure during the redirect pre-flight is reported as passing, not refused."""
    from spyglass_service.radar.reader.redirects import resolve_redirects

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = netguard.guard_client(httpx.Client(transport=httpx.MockTransport(handler)))
    outcome = resolve_redirects(client, "https://example.org/a")
    client.close()
    assert outcome.blocked is True and outcome.transient is True
