"""Tests for the cards REST API used by the dashboard."""

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.models import Card, Feed, Item


def make_client(
    tmp_path: Path,
    open_external: Callable[[str], None] | None = None,
    *,
    skip_startup_embed: bool = True,
) -> TestClient:
    """Build a TestClient for the Spyglass app with an optional fake browser opener.

    open_external: injected in place of webbrowser.open so tests never touch the real browser.
    Existing callers that omit open_external continue to work (defaults to None -> real opener
    is used in production, but tests always supply a fake).
    skip_startup_embed: defaults to True so the lifespan does NOT fire the background
    embed/categorize pass. Tests that need the pass call it explicitly, preventing
    a threadpool race between the startup task and test-seeded 3-dim vectors.
    """
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, open_external=open_external,
                                 skip_startup_embed=skip_startup_embed))


def seed(client: TestClient) -> dict[str, int]:
    """Insert two items and two cards (one rss, one raindrop) via the app engine."""
    engine = client.app.state.engine
    ids: dict[str, int] = {}
    with Session(engine) as session:
        for source in ("rss", "raindrop"):
            item = Item(source=source, external_id=f"e-{source}",
                        title=f"Title {source}", url=f"https://x.test/{source}")
            session.add(item)
            session.commit()
            session.refresh(item)
            card = Card(item_id=item.id, summary=f"summary {source}")
            session.add(card)
            session.commit()
            session.refresh(card)
            ids[source] = card.id
    return ids


def test_cards_list_includes_item_fields(tmp_path: Path) -> None:
    """Cards come back joined with their item's title, url, and source."""
    with make_client(tmp_path) as client:
        seed(client)
        cards = client.get("/api/cards").json()
    assert len(cards) == 2
    sample = cards[0]
    assert {"id", "state", "summary", "title", "url", "source"} <= set(sample)


def test_cards_include_the_item_origin(tmp_path: Path) -> None:
    """Cards expose WHERE an item came from (feed title / site domain), not
    just which collector fetched it."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            item = Item(source="rss", external_id="o-1", title="T",
                        url="https://x.test/o", origin="NVIDIA Technical Blog")
            session.add(item)
            session.commit()
            session.refresh(item)
            session.add(Card(item_id=item.id, summary="s"))
            session.commit()
        card = client.get("/api/cards").json()[0]
    assert card["origin"] == "NVIDIA Technical Blog"


def test_cards_include_relevance_fields(tmp_path: Path) -> None:
    """Cards expose their relevance assessment for the dashboard."""
    with make_client(tmp_path) as client:
        seed(client)
        card = client.get("/api/cards").json()[0]
    assert {"relevance", "relevance_ai", "relevance_reason", "relevance_override",
            "category", "category_ai", "category_override"} <= set(card)


def test_cards_can_be_filtered_by_source_and_state(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        ids = seed(client)
        client.patch(f"/api/cards/{ids['rss']}", json={"state": "reviewed"})
        rss_only = client.get("/api/cards", params={"source": "rss"}).json()
        reviewed = client.get("/api/cards", params={"state": "reviewed"}).json()
    assert [c["source"] for c in rss_only] == ["rss"]
    assert [c["state"] for c in reviewed] == ["reviewed"]


def test_dismissed_cards_are_hidden_by_default_but_never_deleted(tmp_path: Path) -> None:
    """Design rule: dismissed means archived -- out of view, always recoverable."""
    with make_client(tmp_path) as client:
        ids = seed(client)
        client.patch(f"/api/cards/{ids['rss']}", json={"state": "dismissed"})
        default = client.get("/api/cards").json()
        archive = client.get("/api/cards", params={"state": "dismissed"}).json()
    assert len(default) == 1
    assert len(archive) == 1


def test_patch_updates_note_and_prompt_and_bumps_updated_at(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        ids = seed(client)
        before = client.get("/api/cards").json()[0]["updated_at"]
        response = client.patch(
            f"/api/cards/{ids['rss']}",
            json={"note": "for HFM project", "deep_dive_prompt": "focus on QMS"},
        )
        card = response.json()
    assert response.status_code == 200
    assert card["note"] == "for HFM project"
    assert card["deep_dive_prompt"] == "focus on QMS"
    assert card["updated_at"] >= before


def test_patch_unknown_card_returns_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.patch("/api/cards/9999", json={"state": "reviewed"})
    assert response.status_code == 404


def test_patch_rejects_invalid_state(tmp_path: Path) -> None:
    """An unknown state value is a validation error, not a silent write."""
    with make_client(tmp_path) as client:
        ids = seed(client)
        response = client.patch(f"/api/cards/{ids['rss']}", json={"state": "vanished"})
    assert response.status_code == 422


def test_delete_card_endpoint_removes_it(tmp_path: Path) -> None:
    """DELETE /api/cards/{id} returns 200 with deleted=1 and the card no longer appears in GET."""
    with make_client(tmp_path) as client:
        ids = seed(client)
        card_id = ids["rss"]
        response = client.delete(f"/api/cards/{card_id}")
        assert response.status_code == 200
        assert response.json()["deleted"] == 1
        cards = client.get("/api/cards").json()
    assert not any(c["id"] == card_id for c in cards)


def test_delete_unknown_card_is_404(tmp_path: Path) -> None:
    """DELETE /api/cards/9999 returns 404 when the card does not exist."""
    with make_client(tmp_path) as client:
        response = client.delete("/api/cards/9999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Helpers and tests for POST /api/cards/{id}/open-external
# ---------------------------------------------------------------------------

def seed_card(client: TestClient, url: str = "https://x.test") -> int:
    """Insert one Item + Card and return the card_id.

    url: the item's URL (default https://x.test for the happy-path open tests).
    """
    engine = client.app.state.engine
    with Session(engine) as session:
        item = Item(source="rss", external_id="seed-open-1", title="Seed", url=url)
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="seed summary")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id  # type: ignore[return-value]


def test_open_external_opens_card_url(tmp_path: Path) -> None:
    """POST /api/cards/{id}/open-external returns 200 and calls the opener with the item url."""
    opened: list[str] = []
    with make_client(tmp_path, open_external=opened.append) as client:
        card_id = seed_card(client)
        response = client.post(f"/api/cards/{card_id}/open-external")
    assert response.status_code == 200
    body = response.json()
    assert body["opened"] is True
    assert opened == ["https://x.test"]


def test_open_external_rejects_non_http_scheme(tmp_path: Path) -> None:
    """POST /api/cards/{id}/open-external returns 400 for non-http urls and never calls opener."""
    opened: list[str] = []
    with make_client(tmp_path, open_external=opened.append) as client:
        card_id = seed_card(client, url="file:///etc/passwd")
        response = client.post(f"/api/cards/{card_id}/open-external")
    assert response.status_code == 400
    assert opened == []


def test_open_external_unknown_card_is_404(tmp_path: Path) -> None:
    """POST /api/cards/9999/open-external returns 404 for unknown cards."""
    with make_client(tmp_path) as client:
        response = client.post("/api/cards/9999/open-external")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests for PATCH /api/cards/{id}/feedback (thumbs up/down)
# ---------------------------------------------------------------------------

def test_patch_feedback_up(tmp_path: Path) -> None:
    """A thumbs-up persists and is echoed back."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "up"}).json()
    assert result["feedback"] == "up"


def test_patch_feedback_clear(tmp_path: Path) -> None:
    """Setting feedback to null clears it."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "down"})
        result = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": None}).json()
    assert result["feedback"] is None


def test_patch_feedback_invalid_is_422(tmp_path: Path) -> None:
    """A value other than up/down/null is rejected with 422."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        response = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "sideways"})
    assert response.status_code == 422


def test_patch_feedback_unknown_card_is_404(tmp_path: Path) -> None:
    """An unknown card id returns 404."""
    with make_client(tmp_path) as client:
        response = client.patch("/api/cards/9999/feedback", json={"feedback": "up"})
    assert response.status_code == 404


def test_feedback_appears_in_card_list(tmp_path: Path) -> None:
    """The card-list serializer exposes the feedback field for the dashboard."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "up"})
        card = next(c for c in client.get("/api/cards").json() if c["id"] == card_id)
    assert card["feedback"] == "up"


def test_patch_feedback_down_returns_full_card_with_out_pin(tmp_path: Path) -> None:
    """A thumbs-down returns the FULL card (not just {feedback, feedback_at}), incl. the OUT pin.

    A thumb-down pins relevance='out' + override (set_feedback's side effect); the client
    needs the full card to merge that in place instead of reloading the whole list.
    """
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "down"}).json()
    assert result["feedback"] == "down"
    assert result["relevance"] == "out"
    assert result["relevance_override"] is True
    # Full-card shape spot-check (previously only {feedback, feedback_at} was returned).
    assert result["title"] == "Seed"
    assert "summary" in result
    assert "effective_relevance" in result


def test_patch_feedback_up_returns_full_card(tmp_path: Path) -> None:
    """A thumbs-up returns the full card shape, not just {feedback, feedback_at}."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "up"}).json()
    assert result["feedback"] == "up"
    assert result["title"] == "Seed"
    assert "summary" in result
    assert "effective_relevance" in result


def test_patch_feedback_clear_returns_full_card(tmp_path: Path) -> None:
    """Clearing feedback (null) also returns the full card shape."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": "down"})
        result = client.patch(f"/api/cards/{card_id}/feedback", json={"feedback": None}).json()
    assert result["feedback"] is None
    assert result["feedback_at"] is None
    assert result["title"] == "Seed"
    assert "summary" in result
    assert "effective_relevance" in result


# ---------------------------------------------------------------------------
# Tests for PATCH /api/cards/{id}/relevance (editable override)
# ---------------------------------------------------------------------------


def test_patch_relevance_sets_value_and_override(tmp_path: Path) -> None:
    """Setting a relevance value marks it as an editable user override."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        result = client.patch(
            f"/api/cards/{card_id}/relevance", json={"relevance": "high"}
        ).json()
    assert result["relevance"] == "high"
    assert result["relevance_override"] is True


def test_patch_relevance_clear_reverts_to_ai_baseline(tmp_path: Path) -> None:
    """Clearing (null) reverts the card to its AI baseline and drops the override."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        engine = client.app.state.engine
        with Session(engine) as session:
            card = session.get(Card, card_id)
            card.relevance = "medium"
            card.relevance_ai = "medium"
            session.add(card)
            session.commit()
        client.patch(f"/api/cards/{card_id}/relevance", json={"relevance": "out"})
        result = client.patch(
            f"/api/cards/{card_id}/relevance", json={"relevance": None}
        ).json()
    assert result["relevance"] == "medium"
    assert result["relevance_override"] is False


def test_patch_relevance_unknown_card_is_404(tmp_path: Path) -> None:
    """An unknown card id returns 404."""
    with make_client(tmp_path) as client:
        response = client.patch("/api/cards/9999/relevance", json={"relevance": "high"})
    assert response.status_code == 404


def test_patch_relevance_rejects_invalid_value(tmp_path: Path) -> None:
    """A value outside high/medium/low/out is a 422 validation error, not a silent write."""
    with make_client(tmp_path) as client:
        card_id = seed_card(client)
        response = client.patch(
            f"/api/cards/{card_id}/relevance", json={"relevance": "sideways"}
        )
    assert response.status_code == 422


def test_cards_include_effective_relevance(tmp_path: Path) -> None:
    """GET /api/cards exposes effective_relevance: the prior bucket without thumbs, null when unjudged."""
    from datetime import UTC, datetime

    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            item = Item(source="rss", external_id="er-1", title="J", url="https://x.test/j")
            session.add(item)
            session.commit()
            session.refresh(item)
            session.add(Card(item_id=item.id, summary="s", relevance_score=80,
                             relevance="high", relevance_ai="high", relevance_at=datetime.now(UTC)))
            item2 = Item(source="rss", external_id="er-2", title="U", url="https://x.test/u")
            session.add(item2)
            session.commit()
            session.refresh(item2)
            session.add(Card(item_id=item2.id, summary="s"))  # unjudged
            session.commit()
        cards = client.get("/api/cards").json()
    judged = next(c for c in cards if c["title"] == "J")
    unjudged = next(c for c in cards if c["title"] == "U")
    assert judged["effective_relevance"] == "high"
    assert unjudged["effective_relevance"] is None


# ---------------------------------------------------------------------------
# Tests for GET /api/cards/{id}/similar (similar articles)
# ---------------------------------------------------------------------------


def test_similar_returns_neighbours(tmp_path: Path) -> None:
    """A card's /similar lists its embedding neighbours.

    seed() creates exactly two cards (rss + raindrop). After embedding both, the rss
    card has exactly one neighbour: the raindrop card. The response must list that one
    card by id and no others.
    """
    from spyglass_service.embeddings import embed_pending

    with make_client(tmp_path) as client:
        ids = seed(client)
        # Ensure both cards are embedded (idempotent; lock serializes if lifespan task ran first).
        embed_pending(client.app.state.engine, client.app.state.service_state.ensure_index())
        response = client.get(f"/api/cards/{ids['rss']}/similar")
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == [ids["raindrop"]]


def test_similar_unknown_card_is_404(tmp_path: Path) -> None:
    """An unknown card id yields 404."""
    with make_client(tmp_path) as client:
        assert client.get("/api/cards/9999/similar").status_code == 404


def test_similar_results_carry_a_bounded_rounded_score(tmp_path: Path) -> None:
    """Every similar result includes 'score': a 0..1 cosine rounded to 4dp, ranked
    best-first alongside the usual card fields."""
    from spyglass_service.embeddings import embed_pending

    with make_client(tmp_path) as client:
        ids = seed(client)
        _seed_extra_cards(client, 3)
        embed_pending(client.app.state.engine, client.app.state.service_state.ensure_index())
        rows = client.get(f"/api/cards/{ids['rss']}/similar").json()
    assert len(rows) >= 2
    scores = [row["score"] for row in rows]
    for row in rows:
        assert {"id", "title", "url", "score"} <= set(row)
        assert 0.0 <= row["score"] <= 1.0
        assert row["score"] == round(row["score"], 4)  # 4dp on the wire
        assert row["id"] != ids["rss"]  # the seed card never lists itself
    assert scores == sorted(scores, reverse=True)  # best match first


def test_similar_k_defaults_to_20_and_caps_at_50(tmp_path: Path) -> None:
    """Without k the endpoint returns up to 20 neighbours; k is capped at 50."""
    from spyglass_service.embeddings import embed_pending

    with make_client(tmp_path) as client:
        ids = seed(client)
        _seed_extra_cards(client, 60)  # 62 cards total -> both limits are observable
        embed_pending(client.app.state.engine, client.app.state.service_state.ensure_index())
        seed_id = ids["rss"]
        assert len(client.get(f"/api/cards/{seed_id}/similar").json()) == 20
        assert len(client.get(f"/api/cards/{seed_id}/similar?k=3").json()) == 3
        assert len(client.get(f"/api/cards/{seed_id}/similar?k=999").json()) == 50
        # k <= 0 clamps up to 1 rather than silently collapsing index.similar to one
        # result via its len(out) >= k early stop: a bad param returns a page, not a fluke.
        assert len(client.get(f"/api/cards/{seed_id}/similar?k=0").json()) == 1
        assert len(client.get(f"/api/cards/{seed_id}/similar?k=-5").json()) == 1


def test_similar_without_an_embedding_is_an_empty_list(tmp_path: Path) -> None:
    """A card whose item has no vector yet gets [] (200), never a crash."""
    with make_client(tmp_path) as client:
        ids = seed(client)  # nothing embedded: the index has no vectors at all
        response = client.get(f"/api/cards/{ids['rss']}/similar")
    assert response.status_code == 200
    assert response.json() == []


def test_similar_skips_items_without_cards(tmp_path: Path) -> None:
    """An embedded item that has no card is skipped, not served half-formed."""
    from spyglass_service.embeddings import embed_pending

    with make_client(tmp_path) as client:
        ids = seed(client)
        with Session(client.app.state.engine) as session:
            session.add(Item(source="rss", external_id="cardless", title="No Card",
                             url="https://x.test/cardless"))
            session.commit()
        embed_pending(client.app.state.engine, client.app.state.service_state.ensure_index())
        rows = client.get(f"/api/cards/{ids['rss']}/similar").json()
    assert [row["id"] for row in rows] == [ids["raindrop"]]


def _seed_extra_cards(client: TestClient, n: int) -> None:
    """Insert n additional item+card pairs so similar() has plenty of neighbours."""
    with Session(client.app.state.engine) as session:
        for i in range(n):
            item = Item(source="rss", external_id=f"extra-{i}",
                        title=f"Extra {i}", url=f"https://x.test/extra-{i}")
            session.add(item)
            session.flush()
            session.add(Card(item_id=item.id, summary=f"extra summary {i}"))
        session.commit()


# ---------------------------------------------------------------------------
# Tests for the category review tail: needs-review, review-count,
# confirm-category, + the (now always null/empty) serializer fields.
# ---------------------------------------------------------------------------


def _seed_with_embeddings(client: TestClient) -> dict[str, int]:
    """Seed two cards: one confirmed 'AI', one uncategorized (the review-queue target).

    Embeddings are still attached for parity with the rest of the app, but the centroid
    classifier is retired -- needs_review just lists uncategorized, non-dismissed cards.
    """
    import struct

    engine = client.app.state.engine
    from spyglass_service.models import Embedding

    ids: dict[str, int] = {}
    with Session(engine) as session:
        # Confirmed 'AI' card -- categorized, so NOT in the review queue.
        item_ai = Item(source="rss", external_id="emb-ai", title="AI paper",
                       url="https://x.test/ai")
        session.add(item_ai)
        session.commit()
        session.refresh(item_ai)
        card_ai = Card(item_id=item_ai.id, summary="ai summary",
                       category="AI", category_confirmed=True)
        session.add(card_ai)
        session.commit()
        session.refresh(card_ai)
        vec_ai = struct.pack("3f", 1.0, 0.0, 0.0)
        session.add(Embedding(item_id=item_ai.id, vector=vec_ai, model="fake", dim=3))
        session.commit()
        ids["ai"] = card_ai.id

        # Uncategorized card (no category) -- should appear in needs-review
        item_uc = Item(source="rss", external_id="emb-uc", title="Unknown topic",
                       url="https://x.test/uc")
        session.add(item_uc)
        session.commit()
        session.refresh(item_uc)
        card_uc = Card(item_id=item_uc.id, summary="uc summary")
        session.add(card_uc)
        session.commit()
        session.refresh(card_uc)
        vec_uc = struct.pack("3f", 0.0, 1.0, 0.0)
        session.add(Embedding(item_id=item_uc.id, vector=vec_uc, model="fake", dim=3))
        session.commit()
        ids["uc"] = card_uc.id

    return ids


def test_needs_review_endpoint_returns_queue(tmp_path: Path) -> None:
    """GET /api/cards/needs-review returns uncategorized, non-dismissed cards."""
    with make_client(tmp_path) as client:
        ids = _seed_with_embeddings(client)
        resp = client.get("/api/cards/needs-review")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    card_ids = [r["card_id"] for r in body]
    # The uncategorized card is in the queue; the confirmed one is not.
    assert ids["uc"] in card_ids
    assert ids["ai"] not in card_ids
    # Each entry carries id/item_id/title (no tier/recommendations anymore).
    entry = next(r for r in body if r["card_id"] == ids["uc"])
    assert set(entry) == {"card_id", "item_id", "title"}
    assert entry["title"] == "Unknown topic"


def test_review_count_endpoint(tmp_path: Path) -> None:
    """GET /api/review-count returns the count of cards awaiting review."""
    with make_client(tmp_path) as client:
        _seed_with_embeddings(client)
        resp = client.get("/api/review-count")
    assert resp.status_code == 200
    assert resp.json()["needs_review"] >= 1


def test_confirm_category_endpoint(tmp_path: Path) -> None:
    """POST /api/cards/{id}/confirm-category confirms the card's current category."""
    with make_client(tmp_path) as client:
        ids = _seed_with_embeddings(client)
        # Confirm the AI card's category (it already has one)
        resp = client.post(f"/api/cards/{ids['ai']}/confirm-category")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category_confirmed"] is True


def test_confirm_category_with_override(tmp_path: Path) -> None:
    """POST /api/cards/{id}/confirm-category with {category} changes + confirms the category."""
    with make_client(tmp_path) as client:
        ids = _seed_with_embeddings(client)
        resp = client.post(f"/api/cards/{ids['ai']}/confirm-category",
                           json={"category": "ML"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["category_confirmed"] is True


def test_confirm_category_unknown_card_is_404(tmp_path: Path) -> None:
    """POST /api/cards/9999/confirm-category returns 404 for an unknown card."""
    with make_client(tmp_path) as client:
        resp = client.post("/api/cards/9999/confirm-category")
    assert resp.status_code == 404


def test_cards_serializer_includes_tier_for_uncategorized(tmp_path: Path) -> None:
    """GET /api/cards includes category_tier and category_recommendations for uncategorized cards."""
    with make_client(tmp_path) as client:
        _seed_with_embeddings(client)
        cards = client.get("/api/cards").json()
    uncat = [c for c in cards if c["category"] is None]
    assert uncat, "expected at least one uncategorized card"
    sample = uncat[0]
    assert "category_tier" in sample
    assert "category_recommendations" in sample


def test_cards_serializer_tier_null_for_categorized(tmp_path: Path) -> None:
    """GET /api/cards has category_tier=null for cards that already have a category."""
    with make_client(tmp_path) as client:
        _seed_with_embeddings(client)
        cards = client.get("/api/cards").json()
    cat = [c for c in cards if c["category"] is not None]
    assert cat, "expected at least one categorized card"
    for c in cat:
        assert c["category_tier"] is None
        assert c["category_recommendations"] == []


# ---------------------------------------------------------------------------
# Tests for disabled-feed filter on GET /api/cards
# ---------------------------------------------------------------------------


def _seed_feed_and_cards(engine, feed_url: str = "https://rss.test/feed") -> tuple[int, int]:
    """Insert a Feed + Item + Card for that feed; return (feed_id, card_id).

    Args:
        engine: Active SQLAlchemy engine.
        feed_url: Canonical feed URL used for both Feed.feed_url and Item.feed_url.

    Returns:
        (feed_id, card_id) of the newly created rows.
    """
    with Session(engine) as session:
        feed = Feed(
            feed_url=feed_url,
            name="Test Feed",
            kind="rss",
            added_via="manual",
            enabled=True,
        )
        session.add(feed)
        session.commit()
        session.refresh(feed)

        item = Item(
            source="rss",
            external_id="feed-item-1",
            title="RSS Article",
            url="https://rss.test/article1",
            feed_url=feed_url,
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        card = Card(item_id=item.id, summary="rss summary")
        session.add(card)
        session.commit()
        session.refresh(card)
        return feed.id, card.id


def test_disabled_feed_hides_its_cards(tmp_path: Path) -> None:
    """Cards whose feed is disabled do not appear in GET /api/cards."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed_id, card_id = _seed_feed_and_cards(engine)

        # Confirm the card is visible before disabling.
        resp_before = client.get("/api/cards")
        assert any(c["id"] == card_id for c in resp_before.json())

        # Disable the feed directly in the DB.
        with Session(engine) as session:
            feed = session.get(Feed, feed_id)
            feed.enabled = False  # type: ignore[union-attr]
            session.add(feed)
            session.commit()

        resp_after = client.get("/api/cards")
    assert not any(c["id"] == card_id for c in resp_after.json())


def test_reenabled_feed_restores_cards(tmp_path: Path) -> None:
    """Re-enabling a disabled feed makes its cards visible again."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        feed_id, card_id = _seed_feed_and_cards(engine)

        with Session(engine) as session:
            feed = session.get(Feed, feed_id)
            feed.enabled = False  # type: ignore[union-attr]
            session.add(feed)
            session.commit()

        assert not any(c["id"] == card_id for c in client.get("/api/cards").json())

        with Session(engine) as session:
            feed = session.get(Feed, feed_id)
            feed.enabled = True  # type: ignore[union-attr]
            session.add(feed)
            session.commit()

        resp_after = client.get("/api/cards")
    assert any(c["id"] == card_id for c in resp_after.json())



# ---------------------------------------------------------------------------
# Tests for the lean list payload + GET /api/cards/{id}
# ---------------------------------------------------------------------------


def _seed_long_summary_card(client: TestClient, length: int = 600) -> tuple[int, str]:
    """Insert one item + card whose summary is `length` chars long.

    Returns (card_id, full_summary) so callers can assert against the untruncated original.
    """
    full_summary = "x" * length
    with Session(client.app.state.engine) as session:
        item = Item(source="rss", external_id="long-summary-1", title="Long Summary",
                    url="https://x.test/long")
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary=full_summary)
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id, full_summary  # type: ignore[return-value]


def test_list_truncates_long_summary_to_lean_preview(tmp_path: Path) -> None:
    """GET /api/cards ships only the first 280 chars of a long summary."""
    with make_client(tmp_path) as client:
        card_id, full_summary = _seed_long_summary_card(client)
        cards = client.get("/api/cards").json()
    card = next(c for c in cards if c["id"] == card_id)
    assert len(card["summary"]) == 280
    assert card["summary"] == full_summary[:280]


def test_list_keeps_other_fields_when_summary_truncated(tmp_path: Path) -> None:
    """Truncating summary in the list response leaves every other field intact."""
    with make_client(tmp_path) as client:
        card_id, _full_summary = _seed_long_summary_card(client)
        cards = client.get("/api/cards").json()
    card = next(c for c in cards if c["id"] == card_id)
    assert card["title"] == "Long Summary"
    assert "effective_relevance" in card
    assert "feedback" in card
    assert card["tags"] == []
    assert "category" in card
    assert "created_at" in card


def test_get_single_card_returns_full_untruncated_summary(tmp_path: Path) -> None:
    """GET /api/cards/{id} returns the FULL summary, not the lean list preview."""
    with make_client(tmp_path) as client:
        card_id, full_summary = _seed_long_summary_card(client)
        card = client.get(f"/api/cards/{card_id}").json()
    assert card["summary"] == full_summary
    assert len(card["summary"]) == 600
    assert "effective_relevance" in card


def test_get_single_card_unknown_id_is_404(tmp_path: Path) -> None:
    """GET /api/cards/999999 for an unknown card returns 404."""
    with make_client(tmp_path) as client:
        response = client.get("/api/cards/999999")
    assert response.status_code == 404


def test_needs_review_route_not_shadowed_by_single_card_route(tmp_path: Path) -> None:
    """GET /api/cards/needs-review still resolves to the needs-review endpoint, not
    GET /api/cards/{card_id} (which would 422 trying to int('needs-review'))."""
    with make_client(tmp_path) as client:
        response = client.get("/api/cards/needs-review")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_response_is_valid_json_with_json_content_type(tmp_path: Path) -> None:
    """GET /api/cards returns application/json and a well-formed JSON list body."""
    with make_client(tmp_path) as client:
        seed(client)
        response = client.get("/api/cards")
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2


def test_null_feed_url_items_always_visible(tmp_path: Path) -> None:
    """Items with null feed_url (Raindrop/legacy) always appear regardless of Feed rows."""
    with make_client(tmp_path) as client:
        engine = client.app.state.engine
        with Session(engine) as session:
            item = Item(
                source="raindrop",
                external_id="rd-1",
                title="Raindrop Article",
                url="https://raindrop.test/a",
                feed_url=None,  # no associated feed
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            card = Card(item_id=item.id, summary="raindrop summary")
            session.add(card)
            session.commit()
            session.refresh(card)
            raindrop_card_id = card.id

        # Add a disabled feed; null-feed_url cards must still appear.
        feed_id, _rss_card_id = _seed_feed_and_cards(engine)
        with Session(engine) as session:
            feed = session.get(Feed, feed_id)
            feed.enabled = False  # type: ignore[union-attr]
            session.add(feed)
            session.commit()

        cards = client.get("/api/cards").json()
    card_ids = [c["id"] for c in cards]
    assert raindrop_card_id in card_ids, "null-feed_url card must always be visible"
