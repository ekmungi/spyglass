"""Tests for the cross-site guard: a web page must not make Spyglass act.

A browser puts the page's own address in an Origin header on every cross-site POST. The CORS
setting only stops that page from reading the reply, so the service itself refuses state-changing
requests that name any other site. A request with no Origin header (the Obsidian plugin, Claude,
scripts) is not a browser page and passes.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from spyglass_service import request_guards
from spyglass_service.app import create_app
from spyglass_service.config import Settings

FOREIGN = "https://evil.example"
# The origins the dashboard really uses: the Obsidian app, and a local browser tab on any port.
ALLOWED = ["app://obsidian.md", "http://127.0.0.1:7777", "http://localhost:5173", "http://localhost"]
# Look-alikes and odd values a hostile page could send; none may pass.
REFUSED = [
    FOREIGN,
    "null",
    "",
    "https://localhost:7777",
    "http://localhost.evil.example",
    "http://127.0.0.1.evil.example",
    "http://evil.example/localhost",
    "http://localhost:80a",
    "ftp://localhost",
    "app://obsidian.md.evil.example",
]


def make_client(tmp_path: Path, stops: list[int]) -> TestClient:
    """An app whose shutdown handler records each call, so a refused request is provable."""
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    return TestClient(create_app(settings, shutdown_handler=lambda: stops.append(1)))


def test_a_foreign_site_cannot_stop_the_service(tmp_path: Path) -> None:
    stops: list[int] = []
    with make_client(tmp_path, stops) as client:
        response = client.post("/api/shutdown", headers={"Origin": FOREIGN})
    assert response.status_code == 403
    assert response.json() == {"detail": "cross-site request refused"}
    assert stops == []


def test_a_request_with_no_origin_header_still_stops_the_service(tmp_path: Path) -> None:
    """The Obsidian plugin's shutdown call is not a browser page: it sends no Origin."""
    stops: list[int] = []
    with make_client(tmp_path, stops) as client:
        response = client.post("/api/shutdown")
    assert response.status_code == 202
    assert stops == [1]


@pytest.mark.parametrize("origin", ALLOWED)
def test_the_dashboards_own_origins_are_let_through(tmp_path: Path, origin: str) -> None:
    stops: list[int] = []
    with make_client(tmp_path, stops) as client:
        response = client.post("/api/shutdown", headers={"Origin": origin})
    assert response.status_code == 202
    assert stops == [1]


@pytest.mark.parametrize("origin", REFUSED)
def test_look_alike_and_odd_origins_are_refused(tmp_path: Path, origin: str) -> None:
    stops: list[int] = []
    with make_client(tmp_path, stops) as client:
        response = client.post("/api/shutdown", headers={"Origin": origin})
    assert response.status_code == 403
    assert stops == []


def test_one_foreign_origin_among_several_is_enough_to_refuse(tmp_path: Path) -> None:
    stops: list[int] = []
    with make_client(tmp_path, stops) as client:
        response = client.post("/api/shutdown",
                               headers=[("Origin", "app://obsidian.md"), ("Origin", FOREIGN)])
    assert response.status_code == 403
    assert stops == []


@pytest.mark.parametrize("path", ["/api/refresh", "/api/briefs/generate", "/mcp/"])
def test_other_post_endpoints_refuse_a_foreign_site_too(tmp_path: Path, path: str) -> None:
    """The hole is the class, not one endpoint: refresh and brief composition ran for a foreign
    Origin, and the mounted MCP endpoint sits behind the same check."""
    with make_client(tmp_path, []) as client:
        response = client.post(path, headers={"Origin": FOREIGN})
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", [("patch", "/api/settings"), ("delete", "/api/feeds/1"),
                                         ("put", "/api/settings")])
def test_every_state_changing_method_is_checked(tmp_path: Path, method: str, path: str) -> None:
    with make_client(tmp_path, []) as client:
        refused = getattr(client, method)(path, headers={"Origin": FOREIGN})
        passed = getattr(client, method)(path)
    assert refused.status_code == 403
    assert passed.status_code != 403


def test_reads_are_not_touched(tmp_path: Path) -> None:
    """GET is not state-changing; CORS already stops a foreign page from reading the reply."""
    with make_client(tmp_path, []) as client:
        response = client.get("/api/health", headers={"Origin": FOREIGN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_a_preflight_from_the_obsidian_app_is_still_answered(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        response = client.options(
            "/api/shutdown",
            headers={"Origin": "app://obsidian.md", "Access-Control-Request-Method": "POST"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://obsidian.md"


def test_the_cors_setting_and_the_guard_share_one_allowlist(tmp_path: Path) -> None:
    """So the two cannot drift apart: both read the constants in request_guards."""
    with make_client(tmp_path, []) as client:
        cors = [m for m in client.app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] == [request_guards.ALLOWED_ORIGIN]
    assert cors[0].kwargs["allow_origin_regex"] == request_guards.ALLOWED_ORIGIN_REGEX


@pytest.mark.parametrize("origin", ALLOWED)
def test_origin_allowed_accepts_the_dashboards_origins(origin: str) -> None:
    assert request_guards.origin_allowed(origin)


@pytest.mark.parametrize("origin", REFUSED)
def test_origin_allowed_refuses_the_rest(origin: str) -> None:
    assert not request_guards.origin_allowed(origin)


@pytest.mark.parametrize("origin", ["http://localhost\n", "http://localhost:7777\n", " http://localhost",
                                    "http://localhost:٣"])
def test_origin_allowed_matches_the_whole_value_in_ascii(origin: str) -> None:
    """A trailing newline, a leading space or a non-ASCII digit must not slip through the pattern."""
    assert not request_guards.origin_allowed(origin)
