"""Tests for CORS: the Obsidian plugin and browsers call the API cross-origin."""

from pathlib import Path

from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path / "data")))


def test_health_allows_the_obsidian_origin(tmp_path: Path) -> None:
    """The plugin runs at app://obsidian.md and must receive an allow-origin header."""
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Origin": "app://obsidian.md"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://obsidian.md"


def test_localhost_browser_origin_is_allowed(tmp_path: Path) -> None:
    """Opening the dashboard in a plain browser tab must also be permitted."""
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_preflight_for_a_patch_is_answered(tmp_path: Path) -> None:
    """A CORS preflight for the card PATCH must succeed so triage works in a browser."""
    with make_client(tmp_path) as client:
        response = client.options(
            "/api/cards/1",
            headers={
                "Origin": "app://obsidian.md",
                "Access-Control-Request-Method": "PATCH",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://obsidian.md"


def test_unrelated_origin_is_not_allowed(tmp_path: Path) -> None:
    """A random external site must not receive an allow-origin header."""
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in response.headers
