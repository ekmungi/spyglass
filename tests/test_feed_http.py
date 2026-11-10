"""Tests for how feeds are fetched and why they fail, against a local web server."""

import http.server
import threading
from pathlib import Path

import pytest
from reader import make_reader

from spyglass_service.feed_http import BROWSER_USER_AGENT, classify_feed_error, use_browser_user_agent
from spyglass_service.feed_registry import NotAFeedError, _validate_feed

FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Guarded feed</title>
<item><title>One</title><link>https://example.org/1</link></item></channel></rss>"""


class Handler(http.server.BaseHTTPRequestHandler):
    """/guarded serves the feed only to browsers; /<code> answers that status; /page is HTML."""

    seen: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 -- http.server API
        agent = self.headers.get("User-Agent", "")
        Handler.seen.append(agent)
        if self.path == "/guarded":
            ok = agent.startswith("Mozilla/")
            self.send_response(200 if ok else 403)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            if ok:
                self.wfile.write(FEED)
            return
        if self.path == "/page":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>hello</body></html>")
            return
        self.send_response(int(self.path.strip("/")))
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def test_reader_sends_the_browser_user_agent_on_the_wire(server, tmp_path: Path) -> None:
    Handler.seen.clear()
    with make_reader(str(tmp_path / "r.db"), feed_root="") as reader:
        use_browser_user_agent(reader)
        reader.add_feed(f"{server}/guarded")
        reader.update_feeds(workers=1)
        feed = reader.get_feed(f"{server}/guarded")
    assert feed.last_exception is None
    assert feed.title == "Guarded feed"
    assert Handler.seen[0] == BROWSER_USER_AGENT


def test_a_feed_that_blocks_unknown_clients_can_be_added(server, tmp_path: Path) -> None:
    assert _validate_feed(f"{server}/guarded", tmp_path / "v.db") == ("Guarded feed", "rss")


@pytest.mark.parametrize(
    ("path", "kind", "words"),
    [
        ("/403", "blocked", "HTTP 403"),
        ("/429", "blocked", "HTTP 429"),
        ("/404", "unreachable", "HTTP 404"),
        ("/500", "unreachable", "HTTP 500"),
        ("/page", "not_a_feed", "Discover"),
    ],
)
def test_failures_are_told_apart(server, tmp_path: Path, path: str, kind: str, words: str) -> None:
    with pytest.raises(NotAFeedError) as caught:
        _validate_feed(f"{server}{path}", tmp_path / "v.db")
    assert caught.value.kind == kind
    assert words in caught.value.reason


def test_a_refused_connection_is_unreachable(tmp_path: Path) -> None:
    with pytest.raises(NotAFeedError) as caught:
        _validate_feed("http://127.0.0.1:1/feed", tmp_path / "v.db")
    assert caught.value.kind == "unreachable"


def test_classification_reads_the_recorded_text() -> None:
    assert classify_feed_error("unknown feed type: 'x'")[0] == "not_a_feed"
    assert classify_feed_error("ReadTimeout: Read timed out.")[0] == "unreachable"
    assert classify_feed_error("SSLError: certificate verify failed")[0] == "unreachable"


def test_the_error_carries_a_plain_reason() -> None:
    blocked = NotAFeedError("https://x.test/feed", "blocked")
    assert blocked.kind == "blocked" and "refused" in blocked.reason
    assert NotAFeedError("https://x.test").kind == "not_a_feed"
