"""Tests for MCP mounting and the dashboard selection endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings))


def test_mcp_endpoint_is_mounted(tmp_path: Path) -> None:
    """/mcp answers (with a protocol error, not a 404): the server is reachable."""
    with make_client(tmp_path) as client:
        response = client.get("/mcp")
    assert response.status_code != 404


def test_selection_roundtrip_via_rest(tmp_path: Path) -> None:
    """The dashboard posts a selection; the same selection reads back."""
    with make_client(tmp_path) as client:
        post = client.post("/api/selection", json={"card_ids": [4, 7]})
        got = client.get("/api/selection").json()
    assert post.status_code == 200
    assert got["card_ids"] == [4, 7]
    assert got["updated_at"] is not None


def test_selection_defaults_to_empty(tmp_path: Path) -> None:
    """Before any selection the endpoint reports an empty list, not an error."""
    with make_client(tmp_path) as client:
        got = client.get("/api/selection").json()
    assert got["card_ids"] == []
