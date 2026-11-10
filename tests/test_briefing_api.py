"""Tests for reading briefings and opening Claude desktop sessions."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, CardState, Item


def make_app(tmp_path: Path, opened: list | None = None):
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    opener = opened.append if opened is not None else (lambda url: None)
    return create_app(settings, link_opener=opener), settings


def seed_finished_card(client: TestClient, settings: Settings) -> int:
    briefing = settings.vault_path / "b.md"
    briefing.write_text("# Briefing body", encoding="utf-8")
    with Session(client.app.state.engine) as session:
        item = Item(source="rss", external_id="x", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        card = Card(
            item_id=item.id, summary="s", state=CardState.FINISHED,
            briefing_path=str(briefing),
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def test_briefing_endpoint_returns_markdown(tmp_path: Path) -> None:
    app, settings = make_app(tmp_path)
    with TestClient(app) as client:
        card_id = seed_finished_card(client, settings)
        response = client.get(f"/api/cards/{card_id}/briefing")
    assert response.status_code == 200
    assert response.json()["markdown"] == "# Briefing body"


def test_briefing_endpoint_leaves_out_the_properties_block(tmp_path: Path) -> None:
    app, settings = make_app(tmp_path)
    with TestClient(app) as client:
        card_id = seed_finished_card(client, settings)
        (settings.vault_path / "b.md").write_text(
            "---\ntitle: T\ntags:\n- spyglass\n---\n\nThe body.\n", encoding="utf-8")
        response = client.get(f"/api/cards/{card_id}/briefing")
    assert response.json()["markdown"] == "The body."


def test_briefing_missing_returns_404(tmp_path: Path) -> None:
    app, settings = make_app(tmp_path)
    with TestClient(app) as client:
        with Session(client.app.state.engine) as session:
            item = Item(source="rss", external_id="x", title="T", url="https://x.test")
            session.add(item)
            session.commit()
            card = Card(item_id=item.id, summary="s")
            session.add(card)
            session.commit()
            session.refresh(card)
            card_id = card.id
        response = client.get(f"/api/cards/{card_id}/briefing")
    assert response.status_code == 404


def test_briefing_outside_vault_is_refused(tmp_path: Path) -> None:
    """Path traversal protection: only files inside the vault are served."""
    app, settings = make_app(tmp_path)
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    with TestClient(app) as client:
        card_id = seed_finished_card(client, settings)
        with Session(client.app.state.engine) as session:
            card = session.get(Card, card_id)
            card.briefing_path = str(outside)
            session.add(card)
            session.commit()
        response = client.get(f"/api/cards/{card_id}/briefing")
    assert response.status_code == 403


def link_params(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    assert url.startswith("claude://code/new?")
    return {key: values[0] for key, values in parse_qs(parsed.query).items()}


def test_open_claude_opens_a_desktop_session_in_the_vault(tmp_path: Path) -> None:
    """POST /api/open-claude opens a claude:// link: prompt typed in, vault as folder."""
    opened: list[str] = []
    app, settings = make_app(tmp_path, opened)
    with TestClient(app) as client:
        response = client.post("/api/open-claude", json={"prompt": "work on my selection"})
    assert response.status_code == 200
    assert response.json() == {"opened": True}
    params = link_params(opened[0])
    assert params["q"] == "work on my selection"
    # The link spells a Windows folder in forward slashes with an alternating drive-letter case,
    # so compare the posix spelling without regard to that case.
    assert params["folder"].lower() == settings.vault_path.as_posix().lower()


def test_open_claude_default_prompt_points_at_the_session_menu(tmp_path: Path) -> None:
    """No prompt: the skill-owned session menu; the prompt does not list options."""
    opened: list[str] = []
    app, _ = make_app(tmp_path, opened)
    with TestClient(app) as client:
        client.post("/api/open-claude", json={})
    q = link_params(opened[0])["q"]
    assert "spyglass skill" in q and "session menu" in q
    assert "train my preferences" not in q


def test_open_claude_names_the_selected_cards(tmp_path: Path) -> None:
    """The cards selected when the button was pressed are named in the prompt."""
    opened: list[str] = []
    app, settings = make_app(tmp_path, opened)
    with TestClient(app) as client:
        card_id = seed_finished_card(client, settings)
        client.post("/api/selection", json={"card_ids": [card_id]})
        client.post("/api/open-claude", json={"prompt": "Compare the selected cards."})
    assert link_params(opened[0])["q"] == f'Compare the selected cards.\n\nCards: #{card_id} "T"'


def test_open_claude_ignores_the_model(tmp_path: Path) -> None:
    """A link has no model parameter; older dashboards may still send one."""
    opened: list[str] = []
    app, _ = make_app(tmp_path, opened)
    with TestClient(app) as client:
        response = client.post("/api/open-claude", json={"prompt": "p", "model": "haiku"})
    assert response.status_code == 200
    assert "haiku" not in opened[0]


def test_open_claude_hands_off_a_long_prompt(tmp_path: Path) -> None:
    """A transcript too long for a link arrives whole through the hand-off store."""
    opened: list[str] = []
    app, _ = make_app(tmp_path, opened)
    long_prompt = "Continue in Claude.\n" + "line of transcript " * 400
    with TestClient(app) as client:
        client.post("/api/open-claude", json={"prompt": long_prompt})
        q = link_params(opened[0])["q"]
        handoff_id = q.split("id ")[1].split(" ")[0]
        assert app.state.service_state.handoffs.get(handoff_id) == long_prompt
    assert len(opened[0]) <= 2000


def test_open_claude_reports_a_missing_desktop_app(tmp_path: Path) -> None:
    """If the link cannot be opened, the dashboard gets the prompt to copy instead."""
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)

    def broken(url: str) -> None:
        raise OSError("no application is associated with claude://")

    app = create_app(settings, link_opener=broken)
    with TestClient(app) as client:
        response = client.post("/api/open-claude", json={"prompt": "deep dive"})
    assert response.status_code == 502
    assert response.json() == {"error": "claude_desktop_unavailable", "prompt": "deep dive"}


def test_startup_registers_spyglass_in_the_vault(tmp_path: Path) -> None:
    """The vault's .mcp.json gets the spyglass server, so desktop sessions find it."""
    app, settings = make_app(tmp_path, [])
    with TestClient(app):
        pass
    data = json.loads((settings.vault_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["spyglass"]["url"] == f"http://127.0.0.1:{settings.port}/mcp/"


def test_registration_can_be_turned_off(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", vault_path=vault, register_mcp=False
    )
    with TestClient(create_app(settings, link_opener=lambda url: None)):
        pass
    assert not (vault / ".mcp.json").exists()


def test_open_claude_without_vault_is_an_error(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, link_opener=lambda url: None)
    with TestClient(app) as client:
        response = client.post("/api/open-claude", json={})
    assert response.status_code == 409


def test_an_old_env_setting_for_the_terminal_launcher_still_loads(tmp_path: Path, monkeypatch) -> None:
    """SPYGLASS_SPAWN_AUTO went with the terminal launcher; an old .env must not stop startup."""
    monkeypatch.setenv("SPYGLASS_SPAWN_AUTO", "true")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert settings.spawn_auto is True
