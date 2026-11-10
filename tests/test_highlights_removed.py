"""TDD RED->GREEN: verify highlight routes are gone.

RED phase: routes exist and return 200/201 for a valid card.
GREEN phase: routes are removed and return 404.

Note: 405 is also accepted in the assertion because a shadowing parameterised
route can cause method-not-allowed before no-match in some router configs.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Item


def make_client(tmp_path: Path) -> TestClient:
    """Build a TestClient for the Spyglass app."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


def seed_card(client: TestClient) -> int:
    """Insert one item+card and return the card id."""
    engine = client.app.state.engine
    with Session(engine) as session:
        item = Item(source="rss", external_id="a", title="T", url="https://x.test")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id


def test_highlights_endpoints_removed(tmp_path: Path) -> None:
    """GET and POST /api/cards/{id}/highlights must 404 (or 405) after router removal.

    Uses a real seeded card so the response is not masked by the card-not-found
    guard that the old route fired for non-existent cards.
    """
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        # Routes should be gone; 404 is expected. 405 is also acceptable if a
        # parameterised route shadow causes a method-not-allowed match first.
        assert client.get(f"/api/cards/{card_id}/highlights").status_code in (404, 405)
        assert client.post(
            f"/api/cards/{card_id}/highlights",
            json={"quote": "x", "start_offset": 0, "end_offset": 1},
        ).status_code in (404, 405)
