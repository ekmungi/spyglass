"""End-to-end pipeline test: collect -> curate -> queue -> briefing -> read back."""

from pathlib import Path

from fastapi.testclient import TestClient

import spyglass_service.app as app_module
from spyglass_service.app import create_app
from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.curation import CurationResult, apply_curation, get_pending_items
from spyglass_service.mcp_server import ServiceState, save_briefing_for_card


class OneItemCollector:
    """Single-item fake source standing in for RSS/Raindrop."""

    name = "fake"

    def collect(self) -> list[CollectedItem]:
        return [
            CollectedItem(
                source="fake", external_id="e1",
                title="Local-first sync engines", url="https://x.test/sync",
                summary="raw", published_at=None,
            )
        ]


def test_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    monkeypatch.setattr(app_module, "build_collectors", lambda _s, _e: [OneItemCollector()])
    app = create_app(settings)

    with TestClient(app) as client:
        engine = client.app.state.engine

        # 1. Collect: the fake source lands one item.
        assert client.post("/api/refresh").json()["refreshed"] is True

        # 2. Curate (what the Claude session does through MCP).
        pending = get_pending_items(engine)
        assert len(pending) == 1
        apply_curation(engine, [CurationResult(item_id=pending[0].id, summary="matters")])

        # 3. The dashboard shows the card; the user queues a deep dive with a note.
        card = client.get("/api/cards").json()[0]
        client.patch(
            f"/api/cards/{card['id']}",
            json={"state": "queued", "note": "for HFM", "deep_dive_prompt": "focus QMS"},
        )

        # 4. The Claude session saves the briefing; the card flips to finished.
        state: ServiceState = client.app.state.service_state
        save_briefing_for_card(state, card["id"], "Sync engines briefing", "# Findings")

        # 5. The dashboard reads the briefing back, rendered from the vault file.
        finished = client.get("/api/cards", params={"state": "finished"}).json()
        assert len(finished) == 1
        briefing = client.get(f"/api/cards/{card['id']}/briefing").json()
        assert "# Findings" in briefing["markdown"]

        # 6. The activity tab saw the run.
        sources = {run["source"] for run in client.get("/api/runs").json()}
        assert "fake" in sources
