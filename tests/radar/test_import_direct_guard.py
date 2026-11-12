"""The browser extension's direct import through the whole app: the cross-site guard's second
exemption, who may use the route, and the cross-origin rules. No test touches the network."""

import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.db import init_db
from spyglass_service.radar import netguard
from spyglass_service.radar.import_key import button_key

from .test_importer import PAGE, URL

DIRECT = "/api/radar/import/direct"
CHECK = DIRECT + "/check"
EXTENSION = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the import path must not use the network")

    monkeypatch.setattr(netguard, "resolve", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


# --- the whole app: the cross-site guard and the cross-origin rules --------------------------


@pytest.fixture()
def whole(tmp_path):
    """The real app, without its background work."""
    vault = tmp_path / "vault"
    vault.mkdir()
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault))
    init_db(app.state.engine)  # no lifespan here, so the tables are made by hand
    yield TestClient(app, follow_redirects=False)
    app.state.engine.dispose()


def test_an_extension_can_post_to_the_direct_route_through_the_whole_app(whole) -> None:
    key = button_key(whole.app.state.settings.data_dir)
    response = whole.post(DIRECT, json={"url": URL, "html": PAGE, "kind": "page"},
                          headers={"Origin": EXTENSION, "X-Spyglass-Key": key})
    assert response.status_code == 200
    assert whole.get(CHECK, headers={"Origin": EXTENSION, "X-Spyglass-Key": key}).status_code == 200


@pytest.mark.parametrize("origin", ["https://news.example.com", "http://evil.example", "null",
                                    "http://localhost.evil.example"])
def test_a_web_page_cannot_use_the_direct_route_even_with_the_key(whole, origin) -> None:
    key = button_key(whole.app.state.settings.data_dir)
    response = whole.post(DIRECT, json={"url": URL, "html": PAGE, "kind": "page"},
                          headers={"Origin": origin, "X-Spyglass-Key": key})
    assert response.status_code == 403


def test_a_web_page_without_the_key_is_refused(whole) -> None:
    response = whole.post(DIRECT, json={"url": URL, "html": PAGE}, headers={"Origin": "https://news.example.com"})
    assert response.status_code == 403


def test_a_browser_preflight_from_another_site_is_not_approved(whole) -> None:
    """The key travels in a custom header, which a web page can only send after an approved
    preflight; the service's CORS setting approves only local pages and Obsidian."""
    response = whole.options(DIRECT, headers={
        "Origin": "https://news.example.com", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-spyglass-key,content-type"})
    assert "access-control-allow-origin" not in response.headers
    assert response.status_code == 400


def test_an_extension_origin_is_refused_on_every_other_state_changing_route(whole) -> None:
    for method, path in [("post", "/api/radar/import/text"), ("post", "/api/radar/import/button-key/rotate"),
                         ("post", "/api/radar/collect"), ("post", "/api/shutdown"),
                         ("delete", "/api/radar/import/staged/" + "0" * 32)]:
        response = getattr(whole, method)(path, headers={"Origin": EXTENSION})
        assert response.status_code == 403, (method, path)


def test_the_key_route_stays_closed_to_an_extension_origin(whole) -> None:
    """The key is only readable by Spyglass's own pages: an extension that lacks it cannot fetch it."""
    response = whole.get("/api/radar/import/button-key", headers={"Origin": EXTENSION, "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
