"""A feed address must be a web address: local paths and `file:` addresses are refused.

The feed library can read a feed from a file on this computer. Spyglass never needs that, and a
feed list that names a path would make the service read local files, so every place that makes a
feed reader turns local feeds off and the registry refuses such an address with a plain reason.
"""

import http.server
import logging
import threading
from pathlib import Path

import pytest
from sqlmodel import Session

from spyglass_service.collectors.rss import RssCollector
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.feed_http import REASONS, is_web_feed_address
from spyglass_service.feed_registry import NotAFeedError, _validate_feed, add_feed, list_feeds

FEED = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
REASON = "Spyglass reads feeds from the web only."


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the sample feed at /feed.xml."""

    def do_GET(self) -> None:  # noqa: N802 -- http.server API
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.end_headers()
        self.wfile.write(FEED)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def feed_server():
    """The sample feed on a web server on this computer; the address guard is told it is public."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/feed.xml"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def loopback_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same exemption as the feed fetching tests: the guard's address decision is replaced."""
    from spyglass_service.radar import netguard

    monkeypatch.setattr(netguard, "check_url", lambda url, resolver=None: netguard.Reach.PUBLIC)
    monkeypatch.setattr(netguard, "checked_addresses", lambda host: [host])


@pytest.fixture()
def session(tmp_path: Path):
    """A database session; the engine is disposed afterwards."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.mark.parametrize("address", [
    "https://example.org/feed.xml", "http://example.org/rss", "HTTPS://Example.org/Feed",
])
def test_a_web_address_is_a_web_feed_address(address: str) -> None:
    assert is_web_feed_address(address)


@pytest.mark.parametrize("address", [
    "", "   ", "/etc/passwd", "../secrets/feed.xml", r"..\feed.xml", "feed.xml",
    r"C:\feeds\a.xml", "file:///etc/passwd", "FILE:///C:/x/feed.xml",
    "file:feed.xml", "http:", "http:///path", "ftp://example.org/feed.xml",
])
def test_anything_else_is_not(address: str) -> None:
    assert not is_web_feed_address(address)


@pytest.mark.parametrize("address", [
    "/etc/passwd", "../secrets/feed.xml", "file:///etc/passwd", r"C:\feeds\a.xml",
])
def test_adding_a_local_address_is_refused_with_a_plain_reason(session: Session, tmp_path: Path,
                                                                address: str) -> None:
    with pytest.raises(NotAFeedError) as caught:
        add_feed(session, address, reader_db_path=tmp_path / "r.db")
    assert caught.value.reason == REASON == REASONS["local_file"]
    assert caught.value.kind == "local_file"
    assert list_feeds(session) == []


def test_the_validator_itself_refuses_a_local_address(tmp_path: Path) -> None:
    sample = Path(__file__).parent / "fixtures" / "sample_feed.xml"
    for address in (str(sample), sample.as_uri()):
        with pytest.raises(NotAFeedError) as caught:
            _validate_feed(address, tmp_path / "v.db")
        assert caught.value.reason == REASON


def test_a_web_feed_still_validates_and_is_added(session: Session, tmp_path: Path, feed_server: str,
                                                  loopback_allowed: None) -> None:
    feed = add_feed(session, feed_server, reader_db_path=tmp_path / "r.db")
    assert feed.feed_url == feed_server
    assert feed.name == "Sample Research Feed"


def test_the_collector_skips_a_stored_local_feed_and_reads_the_web_one(
        tmp_path: Path, feed_server: str, loopback_allowed: None, caplog) -> None:
    sample = Path(__file__).parent / "fixtures" / "sample_feed.xml"
    collector = RssCollector([str(sample), sample.as_uri(), feed_server], tmp_path / "reader.db")
    with caplog.at_level(logging.WARNING, logger="spyglass_service.collectors.rss"):
        items = collector.collect()
    assert items and all(i.feed_url == feed_server for i in items)
    skipped = [r for r in caplog.records if "not a web address" in r.getMessage()]
    assert len(skipped) == 2
