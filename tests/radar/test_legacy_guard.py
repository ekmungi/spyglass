"""The older collectors and fetch paths (outside `radar/`) reach the network only through the guard.

Each test names one call site that used to bypass the address check and shows it now refuses a
private address, a redirect to one, or an address that moves between the check and the connection.
No test touches the network: private targets are refused before any connection is made, and
public ones go to a mock transport.
"""

import io
import socket
from types import SimpleNamespace

import httpx
import pytest
import requests
from reader import make_reader
from sqlmodel import Session, select

from spyglass_service import documents, feed_discovery, fetch_acquire, fetch_rungs
from spyglass_service.collectors.rss import RssCollector, resolve_feed_url, write_feed_health
from spyglass_service.extractors import transcript
from spyglass_service.feed_http import classify_feed_error, use_browser_user_agent
from spyglass_service.models import Feed
from spyglass_service.radar import netguard, netreq
from spyglass_service.radar.netguard import BlockedAddress

from .test_sources_support import make_engine

PRIVATE_FEED = "http://10.1.2.3/feed.xml"


# ---- the feed library's own HTTP session -------------------------------------------------------


def _session_of(reader) -> requests.Session:
    """The requests session the reader uses for http(s) feeds, after its lazy set-up has run."""
    reader._parser.do_lazy_init()
    return reader._parser.get_retriever("https://").session


def test_a_reader_session_refuses_a_private_address(tmp_path) -> None:
    """Adding the guard makes the session raise before connecting to a private feed address."""
    with make_reader(str(tmp_path / "r.db"), feed_root="") as reader:
        use_browser_user_agent(reader)
        session = _session_of(reader)
        for url in (PRIVATE_FEED, "http://127.0.0.1:8080/x", "http://localhost/x",
                    "http://[::1]/x", "https://192.168.0.9/x"):
            with pytest.raises(netreq.BlockedFeedAddress, match="cannot be fetched"):
                session.get(url)


def test_a_reader_session_checks_every_redirect_hop(tmp_path, monkeypatch) -> None:
    """A public feed that redirects to a private address is stopped at the second hop."""
    sent: list[str] = []

    def fake_send(self, request, **kwargs):
        sent.append(request.url)
        response = requests.Response()
        response.status_code, response.url, response.request = 302, request.url, request
        response.headers["Location"] = PRIVATE_FEED
        response.raw, response._content = io.BytesIO(b""), b""
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    with make_reader(str(tmp_path / "r.db"), feed_root="") as reader:
        use_browser_user_agent(reader)
        session = _session_of(reader)
        with pytest.raises(netreq.BlockedFeedAddress):
            session.get("https://feeds.example.org/rss")
    assert sent == ["https://feeds.example.org/rss"]  # the private hop was never requested


def test_a_name_that_cannot_be_looked_up_is_a_passing_failure(tmp_path, monkeypatch) -> None:
    """A lookup failure reads as 'could not be reached', not as a refused address."""
    def no_lookup(_host):
        raise OSError("no such host")

    monkeypatch.setattr(netguard, "resolve", no_lookup)
    monkeypatch.setattr(netguard, "_sleep", lambda _s: None)
    netguard.clear_lookup_cache()
    with make_reader(str(tmp_path / "r.db"), feed_root="") as reader:
        use_browser_user_agent(reader)
        with pytest.raises(requests.exceptions.ConnectionError, match="could not be reached"):
            _session_of(reader).get("https://nowhere.example.org/rss")


def test_the_connection_goes_to_the_checked_address(monkeypatch) -> None:
    """The socket is opened to the address that passed the check; the name is kept for TLS."""
    import urllib3.util.connection as urllib_connection

    opened: list[str] = []

    def fake_create(address, *_a, **_k):
        opened.append(address[0])
        return socket.socket()

    monkeypatch.setattr(urllib_connection, "create_connection", fake_create)
    connection = netreq.PinnedHTTPSConnection("feeds.example.org", 443)
    sock = connection._new_conn()
    sock.close()
    assert opened == ["93.184.216.34"]  # the test resolver's public answer, not a fresh lookup
    assert connection.host == "feeds.example.org"  # certificate checks still use the name


def test_a_name_that_turns_private_is_not_connected_to(monkeypatch) -> None:
    """If the name now resolves privately, no connection is attempted."""
    import urllib3.exceptions

    monkeypatch.setattr(netguard, "resolve", lambda _host: ["10.0.0.7"])
    netguard.clear_lookup_cache()
    with pytest.raises(urllib3.exceptions.NewConnectionError):
        netreq.PinnedHTTPConnection("rebind.example.org", 80)._new_conn()


def test_the_adapter_installs_pinned_pools() -> None:
    """Both schemes use the pinned connection classes."""
    adapter = netreq.GuardedAdapter(timeout=5)
    classes = adapter.poolmanager.pool_classes_by_scheme
    assert classes["http"].ConnectionCls is netreq.PinnedHTTPConnection
    assert classes["https"].ConnectionCls is netreq.PinnedHTTPSConnection


def test_a_private_feed_does_not_crash_collection_and_gives_a_plain_reason(tmp_path) -> None:
    """The collector returns nothing for it, and the feed's recorded reason is a plain sentence."""
    engine = make_engine(tmp_path)
    try:
        with Session(engine) as session:
            session.add(Feed(name="Local", feed_url=PRIVATE_FEED, kind="rss", added_via="user"))
            session.commit()
        db = tmp_path / "reader.db"
        assert RssCollector([PRIVATE_FEED], db).collect() == []
        write_feed_health(engine, db)
        with Session(engine) as session:
            row = session.exec(select(Feed)).first()
        assert row.last_fetch_status == "error"
        assert "cannot be fetched" in row.last_error
    finally:
        engine.dispose()


def test_a_refused_feed_address_is_classified_with_a_plain_reason() -> None:
    """The error text from the guard maps to a sentence for the reader, not a stack trace."""
    kind, reason = classify_feed_error("ParseError: while getting feed\nThis address cannot be fetched.")
    assert kind == "blocked" and "private network" in reason


# ---- YouTube handle lookup and feed discovery --------------------------------------------------


def test_resolving_a_youtube_handle_uses_a_guarded_client(monkeypatch) -> None:
    """With no client given, resolve_feed_url builds its own through netguard.page_client."""
    made: list[bool] = []

    def fake_page_client(**_kw):
        made.append(True)
        page = '<html>"channelId":"UCabcdefghijklmnopqrstuv"</html>'
        return netguard.guard_client(httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page))))

    monkeypatch.setattr(netguard, "page_client", fake_page_client)
    url = resolve_feed_url("https://www.youtube.com/@somechannel")
    assert made == [True] and url.endswith("channel_id=UCabcdefghijklmnopqrstuv")


def test_feed_discovery_refuses_a_private_address() -> None:
    """Discovery on a private address fails with a network reason and sends nothing."""
    feed_discovery._CACHE.clear()
    result = feed_discovery.discover("http://192.168.1.1/", 0)
    assert result.candidates == [] and result.reason_code is not None


# ---- the page and document fetchers ------------------------------------------------------------


def test_the_document_client_is_guarded() -> None:
    """documents.build_client refuses private addresses and sends only reads."""
    client = documents.build_client()
    try:
        with pytest.raises(BlockedAddress):
            client.get("http://169.254.169.254/latest/meta-data")
        with pytest.raises(netguard.RefusedMethod):
            client.post("https://example.org/", content=b"x")
    finally:
        client.close()


def test_guard_client_is_idempotent() -> None:
    """Wrapping a guarded client again adds no second set of hooks."""
    client = netguard.guard_client(httpx.Client())
    hooks = list(client.event_hooks["request"])
    assert netguard.guard_client(client) is client
    assert client.event_hooks["request"] == hooks
    client.close()


def test_acquire_does_not_escalate_after_a_refused_address() -> None:
    """A private address refused at the first rung is not forwarded to any other rung."""
    calls: list[str] = []

    def rung(url: str):
        calls.append(url)
        raise AssertionError("must not run")

    rung.tier = "T2"
    client = netguard.guard_client(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200))))
    result = fetch_acquire.acquire("http://10.0.0.5/admin", client=client, rungs=[rung])
    client.close()
    assert not result.ok and calls == [] and "cannot be fetched" in result.error


def test_the_default_ladder_follows_redirects_by_hand(monkeypatch) -> None:
    """With no rungs given, the curl rung is the guarded one and refuses a private address."""
    curl_calls: list[str] = []
    monkeypatch.setattr(fetch_rungs, "_acquire_curl_cffi",
                        lambda url, **_k: curl_calls.append(url))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    result = fetch_acquire.acquire("http://10.0.0.5/page", client=client)
    client.close()
    assert curl_calls == [] and not result.ok and "cannot be fetched" in result.error


def test_build_rungs_is_guarded_unless_asked_otherwise() -> None:
    """The settings-built ladder uses the guarded curl rung by default."""
    settings = SimpleNamespace(jina_enabled=False, browser_enabled=False)
    rung = fetch_rungs.build_rungs(settings)[0]
    assert rung is not fetch_acquire._acquire_curl_cffi
    assert fetch_rungs.build_rungs(settings, guarded=False)[0] is fetch_acquire._acquire_curl_cffi


def test_the_transcript_command_is_not_given_an_internal_address() -> None:
    """The transcript tool is only run for web addresses that are not on this computer."""
    ran: list[list[str]] = []

    def runner(args):
        ran.append(args)
        return SimpleNamespace(stdout='{"text": "hello"}')

    assert transcript._fetch_transcript_via_cli("http://127.0.0.1/v", runner=runner) is None
    assert transcript._fetch_transcript_via_cli("file:///etc/passwd", runner=runner) is None
    assert ran == []
    assert transcript._fetch_transcript_via_cli("https://vimeo.com/1", runner=runner) == "hello"
