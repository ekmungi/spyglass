"""Tests for user taxonomy endpoints: categories + per-card relevance/category override."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Item


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings))


def seed_card(client: TestClient) -> int:
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


def test_create_and_list_categories(tmp_path: Path) -> None:
    """A created category persists with zero cards and is listed."""
    with make_client(tmp_path) as client:
        assert client.post("/api/categories", json={"name": "New Topic"}).status_code == 201
        cats = client.get("/api/categories").json()
    new = next(c for c in cats if c["name"] == "New Topic")
    assert new["count"] == 0


def test_patch_card_category_recategorizes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(f"/api/cards/{card_id}/category", json={"category": "Healthcare AI"}).json()
    assert result["category"] == "Healthcare AI"


def test_patch_card_relevance_overrides(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(f"/api/cards/{card_id}/relevance", json={"relevance": "low"}).json()
    assert result["relevance"] == "low"


def test_rename_category_updates_cards_and_baselines(tmp_path: Path) -> None:
    """Renaming a category renames the managed row AND both card fields, so the
    net-change override state is preserved across the rename."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        engine = client.app.state.engine
        with Session(engine) as session:
            card = session.get(Card, card_id)
            card.category = "Misc"
            card.category_ai = "Misc"
            session.add(card)
            session.commit()
        client.post("/api/categories", json={"name": "Misc"})
        response = client.patch("/api/categories/Misc", json={"name": "Miscellaneous"})
        assert response.status_code == 200
        cats = [c["name"] for c in client.get("/api/categories").json()]
        card_json = next(c for c in client.get("/api/cards").json() if c["id"] == card_id)
    assert "Miscellaneous" in cats and "Misc" not in cats
    assert card_json["category"] == "Miscellaneous"
    assert card_json["category_ai"] == "Miscellaneous"
    assert card_json["category_override"] is False


def test_rename_unknown_category_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert (
            client.patch("/api/categories/Nope", json={"name": "X"}).status_code == 404
        )


def test_delete_category_removes_it_and_rebuckets(tmp_path: Path) -> None:
    """DELETE /api/categories/{name} removes the managed category and re-buckets its
    cards to Unsorted: the card's category clears and it drops off the list."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        client.patch(f"/api/cards/{card_id}/category", json={"category": "Robotics"})
        assert "Robotics" in {c["name"] for c in client.get("/api/categories").json()}

        resp = client.delete("/api/categories/Robotics")
        assert resp.status_code == 200

        cats = {c["name"] for c in client.get("/api/categories").json()}
        card_json = next(c for c in client.get("/api/cards").json() if c["id"] == card_id)
    assert "Robotics" not in cats
    assert card_json["category"] is None


def test_delete_unknown_category_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.delete("/api/categories/Nope").status_code == 404


def test_patch_unknown_card_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.patch("/api/cards/9999/category", json={"category": "X"}).status_code == 404
        assert client.patch("/api/cards/9999/relevance", json={"relevance": "low"}).status_code == 404


def test_categories_order_endpoint_removed(tmp_path: Path) -> None:
    """PUT /api/categories/order no longer exists (drag-to-pin removed).
    FastAPI returns 405 (path matches /{name} but PUT is not registered)."""
    with make_client(tmp_path) as client:
        resp = client.put("/api/categories/order", json={"names": ["A", "B"]})
    assert resp.status_code in (404, 405)
