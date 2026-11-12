"""Images are fetched by the service, not by the reader's browser: the proxy and the rewrite."""

from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import media_proxy, netguard
from spyglass_service.radar.api import media as media_api
from spyglass_service.radar.models import ReaderDoc
from spyglass_service.radar.reader.media import proxied_html

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KNOWN = "https://cdn.example.org/pics/chart.png?w=640&h=480"


@pytest.fixture
def db(tmp_path):
    """A database holding one reader document that shows KNOWN (HTML-escaped, as stored)."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        item = Item(source="rss", external_id="a", title="A story", url="https://example.org/a")
        session.add(item)
        session.commit()
        session.refresh(item)
        escaped = KNOWN.replace("&", "&amp;")
        session.add(ReaderDoc(item_id=item.id, html=f'<p>x</p><img src="{escaped}" alt="c">',
                              lead_image="https://cdn.example.org/lead.jpg"))
        session.commit()
    media_proxy.clear_memo()
    yield engine
    engine.dispose()


class _Seen(list):
    """Recorded requests, plus canned answers by address."""

    answers: dict


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> _Seen:
    """Answer image fetches locally through a guarded client; record each request."""
    seen = _Seen()
    answers: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers.get(str(request.url)) or httpx.Response(
            200, content=PNG, headers={"content-type": "image/png"})

    monkeypatch.setattr(media_proxy, "_client_factory", lambda: netguard.guard_client(
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)))
    seen.answers = answers
    return seen


def _client(db, tmp_path) -> TestClient:
    """A small app with only the media router."""
    app = FastAPI()
    app.include_router(media_api.router, prefix="/api/radar")
    app.state.engine = db
    app.state.settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(app)


def _get(client: TestClient, url: str, **headers) -> httpx.Response:
    """Ask the proxy for `url`."""
    return client.get(f"/api/radar/img?u={quote(url, safe='')}", headers=headers)


def _is_pixel(response: httpx.Response) -> bool:
    """True for the 1x1 transparent stand-in."""
    return response.status_code == 200 and response.content == media_proxy.PIXEL


def test_a_known_image_is_fetched_once_cached_and_served_safely(db, tmp_path, served) -> None:
    """Served with the image type, private caching and nosniff; the second time from the cache."""
    client = _client(db, tmp_path)
    first = _get(client, KNOWN)
    assert first.status_code == 200 and first.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "private, max-age=86400"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert _get(client, KNOWN).content == PNG
    assert len(served) == 1
    request = served[0]
    assert request.method == "GET" and "cookie" not in request.headers
    assert any((tmp_path / "data" / "img_cache").iterdir())


def test_the_lead_image_counts_as_known(db, tmp_path, served) -> None:
    """The reader document's lead image is served too."""
    assert _get(_client(db, tmp_path), "https://cdn.example.org/lead.jpg").content == PNG


def test_an_address_in_no_reader_document_is_refused_without_a_fetch(db, tmp_path, served) -> None:
    """The proxy is not an open proxy: unknown addresses get the stand-in and nothing is fetched."""
    response = _get(_client(db, tmp_path), "https://tracker.example.net/pixel.gif?u=reader")
    assert _is_pixel(response) and served == []


@pytest.mark.parametrize("content_type", ["text/html", "application/javascript",
                                          "image/svg+xml", "image/svg+xml; charset=utf-8", ""])
def test_non_image_and_svg_answers_are_refused(db, tmp_path, served, content_type) -> None:
    """Only raster images pass; SVG (which can carry script) and everything else is refused."""
    served.answers[KNOWN] = httpx.Response(200, content=b"<svg/>",
                                           headers={"content-type": content_type})
    assert _is_pixel(_get(_client(db, tmp_path), KNOWN))


def test_an_image_over_8_mb_is_refused(db, tmp_path, served) -> None:
    """A declared or actual size over the cap gets the stand-in."""
    big = b"\x00" * (media_proxy.MAX_IMAGE_BYTES + 1)
    served.answers[KNOWN] = httpx.Response(200, content=big,
                                           headers={"content-type": "image/png"})
    assert _is_pixel(_get(_client(db, tmp_path), KNOWN))


def test_a_known_address_that_redirects_to_a_private_one_is_refused(db, tmp_path, served) -> None:
    """The guarded client checks every hop."""
    served.answers[KNOWN] = httpx.Response(
        302, headers={"location": "http://192.168.1.1/cam.jpg"})
    assert _is_pixel(_get(_client(db, tmp_path), KNOWN))
    assert [r.url.host for r in served] == ["cdn.example.org"]


def test_cross_site_requests_are_refused(db, tmp_path, served) -> None:
    """A page on another site cannot use the proxy."""
    response = _get(_client(db, tmp_path), KNOWN, **{"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403 and served == []


def test_a_non_web_address_is_refused(db, tmp_path, served) -> None:
    """file:, data: and over-long addresses never reach a fetch."""
    client = _client(db, tmp_path)
    assert _is_pixel(_get(client, "file:///C:/Windows/win.ini"))
    assert _get(client, "https://cdn.example.org/" + "a" * 5000).status_code in (200, 422)
    assert served == []


def test_the_cache_stays_within_its_bound(tmp_path, monkeypatch) -> None:
    """The least recently used files go first when the cache is over its size."""
    monkeypatch.setattr(media_proxy, "CACHE_BYTES", 250)
    folder = tmp_path / "img_cache"
    for n in range(4):
        media_proxy.cache_put(folder, f"https://cdn.example.org/{n}.png", b"x" * 100, "image/png")
        media_proxy.cache_get(folder, "https://cdn.example.org/0.png")  # keep 0 recently used
    kept = {n for n in range(4) if media_proxy.cache_get(folder, f"https://cdn.example.org/{n}.png")}
    assert 0 in kept and 3 in kept and len(kept) == 2
    total = sum(p.stat().st_size for p in folder.iterdir())
    assert total <= 250 + 100


# ---- the rewrite -------------------------------------------------------------------------------


def test_proxied_html_rewrites_every_image_address() -> None:
    """src and srcset of img and source elements point at the proxy, address URL-encoded."""
    html = ('<p>Hi</p><img src="https://a.example/x.png?a=1&amp;b=2" alt="x">'
            '<picture><source srcset="https://a.example/s.webp 1x, https://a.example/l.webp 2x">'
            '<img src="//cdn.example/y.jpg" srcset="https://a.example/m.jpg 640w"></picture>'
            '<img src="data:image/gif;base64,R0lGOD">')
    out = proxied_html(html, True)
    assert f'/api/radar/img?u={quote("https://a.example/x.png?a=1&b=2", safe="")}' in out
    assert f'/api/radar/img?u={quote("https://a.example/s.webp", safe="")} 1x' in out
    assert f'/api/radar/img?u={quote("https://a.example/l.webp", safe="")} 2x' in out
    assert f'/api/radar/img?u={quote("https://cdn.example/y.jpg", safe="")}' in out
    assert f'/api/radar/img?u={quote("https://a.example/m.jpg", safe="")} 640w' in out
    assert "data:image/gif;base64,R0lGOD" in out
    assert "https://a.example/x.png" not in out.replace(quote("https://a.example/x.png", safe=""), "")


def test_proxied_html_leaves_the_document_alone_when_switched_off() -> None:
    """Off returns the document unchanged; empty input stays empty."""
    html = '<img src="https://a.example/x.png">'
    assert proxied_html(html, False) == html
    assert proxied_html("", True) == ""


def test_proxied_reader_rewrites_html_and_lead_image_without_changing_the_input() -> None:
    """The item-detail reader block is copied with its images pointed at the proxy."""
    from spyglass_service.radar.reader.media import proxied_reader

    block = {"html": '<img src="https://a.example/x.png">', "lead_image": "https://a.example/l.jpg",
             "title": "T"}
    out = proxied_reader(block, True)
    assert out["lead_image"] == "/api/radar/img?u=" + quote("https://a.example/l.jpg", safe="")
    assert "/api/radar/img?u=" in out["html"] and out["title"] == "T"
    assert block["lead_image"] == "https://a.example/l.jpg"
    assert proxied_reader(block, False) is block and proxied_reader(None, True) is None
