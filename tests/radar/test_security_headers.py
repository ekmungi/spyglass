"""The response-header layer: every response is covered, streams are not buffered, PDFs and MCP differ."""

from pathlib import Path
import re

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.security_headers import CONTENT_SECURITY_POLICY, SecurityHeaders, _under


def make_client() -> TestClient:
    """A small app wrapped in the layer, with the response kinds the real service has."""
    app = FastAPI()

    @app.get("/page")
    def page() -> PlainTextResponse:
        return PlainTextResponse("hi")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unhandled")

    @app.get("/pdf")
    def pdf() -> Response:
        return Response(b"%PDF-1.4", media_type="application/pdf")

    @app.get("/mcp/thing")
    def mcp() -> PlainTextResponse:
        return PlainTextResponse("rpc")

    @app.get("/docs")
    def docs() -> PlainTextResponse:
        return PlainTextResponse("swagger")

    @app.get("/own")
    def own() -> Response:
        return Response("x", headers={"Referrer-Policy": "same-origin"})

    @app.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter([b"data: 1\n\n", b"data: 2\n\n"]), media_type="text/event-stream")

    app.add_middleware(SecurityHeaders)
    return TestClient(app, raise_server_exceptions=False)


def test_every_ordinary_response_carries_the_four_headers() -> None:
    headers = make_client().get("/page").headers
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_refusals_and_missing_pages_are_covered_too() -> None:
    client = make_client()
    missing = client.get("/nowhere")
    assert missing.status_code == 404 and missing.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in missing.headers
    # An unhandled exception is answered by Starlette's outermost layer, which no middleware wraps.
    assert client.get("/boom").status_code == 500


def test_the_policy_has_the_required_directives() -> None:
    directives = dict(part.strip().split(" ", 1) for part in CONTENT_SECURITY_POLICY.split(";"))
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"
    assert directives["connect-src"] == "'self'"
    assert directives["object-src"] == "'none'"
    assert directives["base-uri"] == "'self'"
    assert directives["form-action"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["style-src"] == "'self' 'unsafe-inline'"
    assert set(directives["img-src"].split()) >= {"http:", "https:", "data:"}
    assert "https:" in directives["media-src"].split() and "http:" not in directives["media-src"].split()
    frames = directives["frame-src"].split()
    assert "'self'" in frames and "https://player.vimeo.com" in frames
    assert "https://www.youtube-nocookie.com" in frames and "https://www.youtube.com" in frames
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "'unsafe-inline'" not in directives["script-src"]


def test_a_pdf_may_be_framed_by_its_own_site_only_and_gets_no_full_policy() -> None:
    headers = make_client().get("/pdf").headers
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["content-security-policy"] == "frame-ancestors 'self'"
    assert headers["x-content-type-options"] == "nosniff"


def test_the_mcp_path_gets_no_framing_or_content_policy() -> None:
    headers = make_client().get("/mcp/thing").headers
    assert "x-frame-options" not in headers and "content-security-policy" not in headers
    assert headers["x-content-type-options"] == "nosniff"


def test_the_interactive_api_pages_get_no_content_policy_but_still_cannot_be_framed() -> None:
    headers = make_client().get("/docs").headers
    assert "content-security-policy" not in headers and headers["x-frame-options"] == "DENY"


def test_a_header_set_by_the_route_is_kept() -> None:
    assert make_client().get("/own").headers["referrer-policy"] == "same-origin"


def test_streamed_responses_still_stream_with_the_headers() -> None:
    response = make_client().get("/stream")
    assert response.text == "data: 1\n\ndata: 2\n\n"
    assert response.headers["x-frame-options"] == "DENY"


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def test_the_real_app_sends_the_headers_on_the_api_and_the_interface(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, spa_dir=DIST if DIST.is_dir() else None, skip_startup_embed=True)
    with TestClient(app) as client:
        for path in ("/api/health", "/"):
            headers = client.get(path).headers
            assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY, path
            assert headers["x-frame-options"] == "DENY" and headers["referrer-policy"] == "no-referrer"


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="the interface has not been built")
def test_the_built_interface_needs_no_inline_script_or_other_origin() -> None:
    html = (DIST / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b([^>]*)>", html)
    assert scripts and all("src=" in attrs for attrs in scripts)  # script-src 'self' forbids inline code
    assert not re.search(r"(?:src|href)=\"https?://", html)  # nothing is loaded from another origin
    assert not re.search(r"\son[a-z]+=", html)  # no inline event handlers


@pytest.mark.parametrize("path", ["/mcp", "/mcp/x"])
def test_prefix_matching_covers_the_path_and_below_but_not_look_alikes(path: str) -> None:
    assert _under(path, ("/mcp",)) and not _under("/mcpx", ("/mcp",))
