"""The arXiv and news-search fetchers build their client with the guarded page client."""

import httpx
import pytest

from spyglass_service.radar import netguard
from spyglass_service.radar.papers import arxiv
from spyglass_service.radar.watch import _news_fallback


def _use_client(monkeypatch, handler) -> list[float]:
    """Make `netguard.page_client` return a client on a mock transport; return the timeouts asked."""
    asked: list[float] = []

    def fake_page_client(*, timeout: float = 25.0, follow_redirects: bool = True) -> httpx.Client:
        asked.append(timeout)
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(netguard, "page_client", fake_page_client)
    return asked


def test_arxiv_fetch_uses_the_guarded_client(monkeypatch) -> None:
    asked = _use_client(monkeypatch, lambda request: httpx.Response(200, text="<feed/>"))
    assert arxiv._http_fetch("https://export.arxiv.org/api/query?x=1") == "<feed/>"
    assert asked == [30.0]


def test_arxiv_fetch_retries_once_then_raises(monkeypatch) -> None:
    monkeypatch.setattr(arxiv.time, "sleep", lambda _s: None)
    _use_client(monkeypatch, lambda request: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        arxiv._http_fetch("https://export.arxiv.org/api/query?x=1")


def test_news_fetch_uses_the_guarded_client(monkeypatch) -> None:
    asked = _use_client(monkeypatch, lambda request: httpx.Response(200, text="<rss/>"))
    assert _news_fallback._http_fetch("https://news.google.com/rss/search?q=x") == "<rss/>"
    assert asked == [20.0]


def test_news_fetch_raises_on_an_error_status(monkeypatch) -> None:
    _use_client(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        _news_fallback._http_fetch("https://news.google.com/rss/search?q=x")
