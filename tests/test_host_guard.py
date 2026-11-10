"""Tests for the Host check: the service answers only requests addressed to this computer.

A hostile web page can point a domain it owns at 127.0.0.1 after the page has loaded (DNS
rebinding). The browser then treats Spyglass as the page's own site and lets the page read every
reply. The browser still sends the page's domain in the Host header, so the service refuses any
request whose Host is not 127.0.0.1 or localhost.

The test settings also allow "testserver", the host the test client uses for every other test
file; the conftest adds it through the environment, and the default below proves production does
not include it.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spyglass_service.app import create_app
from spyglass_service.config import Settings

# Starlette's own reply to a refused Host; its text tells the refusal apart from any other 400.
REFUSAL = "Invalid host header"
# The addresses the plugin, the dashboard, Claude and scripts really use.
ALLOWED = ["http://127.0.0.1:7777", "http://localhost:7777", "http://127.0.0.1", "http://localhost"]
# Domains a hostile page could own and point at 127.0.0.1, including look-alikes.
REFUSED = [
    "http://attacker.example",
    "http://attacker.example:7777",
    "http://localhost.attacker.example:7777",
    "http://127.0.0.1.attacker.example:7777",
    "http://127.0.0.2:7777",
]


def make_client(tmp_path: Path, base_url: str) -> TestClient:
    """An app whose requests all carry the Host taken from `base_url`."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings), base_url=base_url)


@pytest.mark.parametrize("base_url", REFUSED)
def test_a_request_addressed_to_another_host_is_refused(tmp_path: Path, base_url: str) -> None:
    with make_client(tmp_path, base_url) as client:
        response = client.get("/api/health")
    assert response.status_code == 400
    assert response.text == REFUSAL


def test_a_foreign_host_cannot_read_the_cards(tmp_path: Path) -> None:
    """The card list is the data a rebinding page would be after."""
    with make_client(tmp_path, "http://attacker.example:7777") as client:
        response = client.get("/api/cards")
    assert response.status_code == 400
    assert response.text == REFUSAL


def test_a_foreign_host_cannot_reach_the_mcp_endpoint(tmp_path: Path) -> None:
    with make_client(tmp_path, "http://attacker.example:7777") as client:
        response = client.get("/mcp")
    assert response.status_code == 400
    assert response.text == REFUSAL


@pytest.mark.parametrize("base_url", ALLOWED)
def test_requests_addressed_to_this_computer_are_answered(tmp_path: Path, base_url: str) -> None:
    with make_client(tmp_path, base_url) as client:
        response = client.get("/api/health")
    assert response.status_code == 200


def test_the_mcp_endpoint_still_answers_on_the_address_claude_uses(tmp_path: Path) -> None:
    """Claude reaches the MCP server at http://127.0.0.1:<port>/mcp/ (the vault's .mcp.json)."""
    with make_client(tmp_path, "http://127.0.0.1:7777") as client:
        response = client.get("/mcp")
    assert response.status_code != 404
    assert response.text != REFUSAL


def test_by_default_only_this_computers_names_are_allowed(monkeypatch) -> None:
    """Without the test environment, "testserver" and every other name are refused."""
    monkeypatch.delenv("SPYGLASS_ALLOWED_HOSTS", raising=False)
    assert Settings(_env_file=None).allowed_hosts == ["127.0.0.1", "localhost"]
