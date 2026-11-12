"""The cross-site guard's one exemption: the bookmark button's form may post a page to
POST /api/radar/import/stage from another site. Every other state-changing route stays refused.

These tests run the whole app, so the exemption is checked where it really sits: behind the Host
check and in front of every router.
"""

import re
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from spyglass_service import request_guards
from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.radar import netguard
from spyglass_service.radar.import_key import button_key

from .test_importer import PAGE, URL

FOREIGN = {"Origin": "https://news.example.com", "Sec-Fetch-Site": "cross-site"}
STAGE = "/api/radar/import/stage"
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("no network in these tests")

    monkeypatch.setattr(netguard, "resolve", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture()
def client(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    app = create_app(settings)
    # No lifespan: the service's background work is not started, only the request path runs.
    yield TestClient(app, follow_redirects=False)
    app.state.engine.dispose()


def form(**fields) -> dict:
    data = {"url": URL, "title": "A page", "html": PAGE, **fields}
    return {key: (None, value) for key, value in data.items()}


def test_the_stage_route_accepts_a_form_from_another_site(client) -> None:
    key = button_key(client.app.state.settings.data_dir)
    response = client.post(STAGE, files=form(key=key), headers=FOREIGN)
    assert response.status_code == 303
    assert re.fullmatch(r"/#/import\?token=[0-9a-f]{32}", response.headers["location"])


def test_the_stage_route_refuses_a_form_from_another_site_without_the_key(client) -> None:
    response = client.post(STAGE, files=form(), headers=FOREIGN)
    assert response.status_code == 303 and response.headers["location"] == "/#/import?error=key"
    no_origin = client.post(STAGE, files=form(key=button_key(client.app.state.settings.data_dir)),
                            headers={"Sec-Fetch-Site": "cross-site"})
    assert no_origin.headers["location"] == "/#/import?error=origin"


def test_the_key_routes_are_refused_to_another_site_through_the_whole_app(client) -> None:
    key_url = "/api/radar/import/button-key"
    assert client.get(key_url, headers=FOREIGN).status_code == 403
    assert client.post(key_url + "/rotate", headers=FOREIGN).status_code == 403
    assert client.get(key_url, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_the_exemptions_are_exactly_two_methods_and_paths() -> None:
    """The bookmark button's form post and the browser extension's direct import, nothing else."""
    assert request_guards.CROSS_SITE_EXEMPT == frozenset({("POST", STAGE), ("POST", "/api/radar/import/direct")})


@pytest.mark.parametrize("method,path", [
    ("put", STAGE), ("delete", STAGE), ("patch", STAGE),
    ("post", STAGE + "/"), ("post", "/api/radar/import/stage2"), ("post", "/api/radar/import"),
    ("post", "/api/radar/import/staged/" + "0" * 32 + "/accept"),
    ("delete", "/api/radar/import/staged/" + "0" * 32),
    ("post", "/api/radar/import/text"), ("post", "/api/radar/import/file"),
    ("post", "/API/radar/import/stage"),
])
def test_neighbours_of_the_exempt_route_are_still_refused(client, method: str, path: str) -> None:
    response = getattr(client, method)(path, headers=FOREIGN)
    assert response.status_code == 403
    assert response.json() == {"detail": request_guards.REFUSAL}


def test_every_other_state_changing_route_is_still_refused_from_another_site(client) -> None:
    """Walk every route the app serves and send each state-changing method from a foreign site."""
    checked = 0
    for route in client.app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in route.methods & STATE_CHANGING:
            if (method, route.path) in request_guards.CROSS_SITE_EXEMPT:
                continue
            response = client.request(method, path, headers=FOREIGN)
            assert response.status_code == 403, (method, route.path)
            checked += 1
    assert checked > 40  # the walk really covered the API, not an empty list


def test_the_exempt_route_still_sits_behind_the_host_check(tmp_path: Path) -> None:
    """A rebinding page's own domain in the Host header is refused before the exemption."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings)
    rebinding = TestClient(app, base_url="http://attacker.example:7778", follow_redirects=False)
    response = rebinding.post(STAGE, files=form(), headers=FOREIGN)
    assert response.status_code == 400
    app.state.engine.dispose()


def test_the_stage_route_answers_on_this_computers_address(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings)
    local = TestClient(app, base_url="http://127.0.0.1:7778", follow_redirects=False)
    response = local.post(STAGE, files=form(), headers=FOREIGN)
    assert response.status_code == 303
    app.state.engine.dispose()


def test_the_redirect_carries_the_security_headers(client) -> None:
    response = client.post(STAGE, files=form(), headers=FOREIGN)
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
