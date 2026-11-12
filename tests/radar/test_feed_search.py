# ruff: noqa: F811
"""Tests for finding feed items related to a text or to another item."""

from datetime import timedelta

import numpy as np
import pytest
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.models import Feed, Item
from spyglass_service.radar import feed_search
from spyglass_service.radar.models import Assessment, utcnow

from .test_assist_support import db  # noqa: F401

AXES = ("capsule", "robot", "market")


def axis_vector(text: str) -> np.ndarray:
    """A tiny stand-in for an embedding: one axis per topic word, plus a spare axis."""
    lowered = text.lower()
    raw = np.array([float(w in lowered) for w in AXES] + [0.05], dtype=np.float32)
    return raw / np.linalg.norm(raw)


class FakeIndex:
    """Just enough of EmbeddingIndex: embed_query, nearest, similar, matrix_for."""

    def __init__(self) -> None:
        """Start with no vectors."""
        self.vectors: dict[int, np.ndarray] = {}
        self.dim = 4

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a question."""
        return axis_vector(text)

    def nearest(self, vector: np.ndarray, k: int = 50) -> list[tuple[int, float]]:
        """Closest stored ids, best first."""
        scored = [(i, float(v @ vector)) for i, v in self.vectors.items()]
        return sorted(scored, key=lambda pair: -pair[1])[:k]

    def similar(self, item_id: int, k: int = 5) -> list[tuple[int, float]]:
        """Closest other ids."""
        if item_id not in self.vectors:
            return []
        return [p for p in self.nearest(self.vectors[item_id], k + 1) if p[0] != item_id][:k]

    def matrix_for(self, ids: list[int]):
        """Vectors of the ids that exist."""
        found = [i for i in ids if i in self.vectors]
        return found, np.vstack([self.vectors[i] for i in found]) if found else np.empty((0, 4))


def make_item(session: Session, index: FakeIndex, title: str, *, tier: str | None = "notable",
              topic: str = "", age_days: int = 1, feed_url: str | None = None,
              headline: str | None = None) -> int:
    """Insert an item (and optional assessment) and register its vector from `topic`."""
    when = utcnow() - timedelta(days=age_days)
    item = Item(source="rss", external_id=title, title=title, url=f"https://e.org/{title}",
                feed_url=feed_url, published_at=when, fetched_at=when)
    session.add(item)
    session.commit()
    session.refresh(item)
    if tier:
        session.add(Assessment(item_id=item.id, stage="digest", score=70, tier=tier,
                               section="health", kind="news", headline=headline))
        session.commit()
    index.vectors[item.id] = axis_vector(topic or title)
    return item.id


@pytest.fixture
def world(db):
    """A database with a handful of items and a fake index over them."""
    index = FakeIndex()
    with Session(db) as session:
        ids = {
            "capsule": make_item(session, index, "Capsule endoscopy with AI triage", topic="capsule"),
            "robot": make_item(session, index, "Robot assisted surgery", topic="robot"),
            "out": make_item(session, index, "Capsule study ruled out", tier="out", topic="capsule"),
            "old": make_item(session, index, "Capsule review", topic="capsule", age_days=40),
            "market": make_item(session, index, "Market sizing for imaging", topic="market"),
            "unjudged": make_item(session, index, "Capsule news unjudged", tier=None, topic="capsule"),
        }
        session.add(Feed(feed_url="https://off.example/rss", name="Off", kind="rss", enabled=False,
                         added_via="test"))
        session.commit()
        ids["off"] = make_item(session, index, "Capsule from a muted feed", topic="capsule",
                               feed_url="https://off.example/rss")
        # Matches by words in the title only; its vector points at an unrelated axis.
        ids["lexical"] = make_item(session, index, "Notes on capsule hardware", topic="market")
    yield db, index, ids


def test_related_items_ranks_semantic_hits_and_drops_out_and_muted(world):
    db, index, ids = world
    with Session(db) as session:
        hits = feed_search.related_items(session, index, "capsule endoscopy")
    found = [i for i, _ in hits]
    assert found[0] == ids["capsule"]
    assert ids["out"] not in found and ids["off"] not in found
    assert ids["robot"] not in found and ids["market"] not in found
    assert ids["unjudged"] in found and ids["old"] in found
    assert all(0.0 <= score <= 1.0 for _, score in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_text_hit_without_semantic_match_is_still_found(world):
    db, index, ids = world
    with Session(db) as session:
        hits = feed_search.related_items(session, index, "capsule hardware")
    assert ids["lexical"] in [i for i, _ in hits]


def test_full_text_hit_is_found(world):
    db, index, ids = world
    content_store.store_fulltext(db, item_id=ids["market"],
                                 markdown="A passage about swallowable imaging gadgets.",
                                 source_url="https://e.org/x")
    with Session(db) as session:
        hits = feed_search.related_items(session, index, "swallowable gadgets")
    assert [i for i, _ in hits] == [ids["market"]]


def test_days_limit_and_floor(world):
    db, index, ids = world
    with Session(db) as session:
        recent = feed_search.related_items(session, index, "capsule", days=7)
        assert ids["old"] not in [i for i, _ in recent]
        capped = feed_search.related_items(session, index, "capsule", limit=1)
        assert len(capped) == 1
        strict = feed_search.related_items(session, index, "robot", min_similarity=0.99)
        assert [i for i, _ in strict] == [ids["robot"]]


def test_no_index_falls_back_to_text_and_empty_text_gives_nothing(world):
    db, _index, ids = world
    with Session(db) as session:
        hits = feed_search.related_items(session, None, "capsule endoscopy")
        assert ids["capsule"] in [i for i, _ in hits]
        assert feed_search.related_items(session, None, "   ") == []


def test_unrelated_question_returns_nothing(world):
    db, index, _ids = world
    with Session(db) as session:
        assert feed_search.related_items(session, index, "zebra migration patterns") == []


def test_broken_index_degrades_to_text(world):
    db, index, ids = world

    def boom(_text: str):
        raise RuntimeError("model missing")

    index.embed_query = boom  # type: ignore[method-assign]
    with Session(db) as session:
        hits = feed_search.related_items(session, index, "capsule endoscopy")
    assert ids["capsule"] in [i for i, _ in hits]


def test_related_to_item_excludes_itself_and_filters(world):
    db, index, ids = world
    with Session(db) as session:
        hits = feed_search.related_to_item(session, index, ids["capsule"])
        found = [i for i, _ in hits]
        assert ids["capsule"] not in found
        assert ids["out"] not in found and ids["off"] not in found
        assert ids["old"] in found
        assert feed_search.related_to_item(session, index, 99999) == []


def test_recent_items_orders_by_score_within_days(world):
    db, _index, ids = world
    with Session(db) as session:
        assessment = session.exec(select(Assessment).where(
            Assessment.item_id == ids["robot"])).one()
        assessment.score = 95
        session.add(assessment)
        session.commit()
        picked = feed_search.recent_items(session, days=7, limit=3)
    found = [i for i, _ in picked]
    assert found[0] == ids["robot"]
    assert ids["old"] not in found and ids["out"] not in found and ids["off"] not in found
    assert len(found) == 3


def test_keywords_drop_filler_words():
    assert feed_search.keywords("What do I have about capsule endoscopy?") == [
        "capsule", "endoscopy"]
    assert feed_search.keywords("the a of") == []


def test_embedding_index_nearest_ranks_by_cosine_and_handles_empty():
    from spyglass_service.embeddings import EmbeddingIndex

    index = EmbeddingIndex(lambda texts: np.vstack([axis_vector(t) for t in texts]), "fake", 4)
    assert index.nearest(axis_vector("capsule"), 3) == []
    index.add(1, index.embed_one("capsule"))
    index.add(2, index.embed_one("robot"))
    ranked = index.nearest(index.embed_query("capsule"), 5)
    assert [i for i, _ in ranked] == [1, 2]
    assert ranked[0][1] > 0.99 > ranked[1][1]


class ArcticIndex(FakeIndex):
    """A fake index that reports the built-in model, with fixed scores and a record of queries."""

    model = "snowflake/snowflake-arctic-embed-s"

    def __init__(self, scores: dict[int, float]) -> None:
        """`scores` are returned, best first, for any vector."""
        super().__init__()
        self.scores = scores
        self.queries: list[str] = []

    def embed_query(self, text: str) -> np.ndarray:
        """Record the text that was embedded."""
        self.queries.append(text)
        return super().embed_query(text)

    def nearest(self, vector: np.ndarray, k: int = 50) -> list[tuple[int, float]]:
        """The fixed scores."""
        return sorted(self.scores.items(), key=lambda pair: -pair[1])[:k]

    def matrix_for(self, ids: list[int]):
        """A vector for every id, so the item-to-item search can start from any of them."""
        return list(ids), np.vstack([axis_vector("capsule") for _ in ids])


def test_built_in_model_gets_the_query_prefix_and_its_own_floors(world):
    db, _index, ids = world
    index = ArcticIndex({ids["capsule"]: 0.70, ids["robot"]: 0.58, ids["market"]: 0.50})
    with Session(db) as session:
        found = [i for i, _ in feed_search.related_items(session, index, "zebra migration patterns")]
        assert found == [ids["capsule"]]
        assert index.queries == [feed_search.ARCTIC_QUERY_PREFIX + "zebra migration patterns"]
        looser = [i for i, _ in feed_search.related_items(
            session, index, "zebra migration patterns", min_similarity=0.55)]
        assert looser == [ids["capsule"], ids["robot"]]
        near = {ids["old"]: 0.74, ids["robot"]: 0.66}
        neighbours = [i for i, _ in feed_search.related_to_item(
            session, ArcticIndex(near), ids["capsule"])]
        assert neighbours == [ids["old"]]


def test_other_models_use_the_general_floor_and_no_prefix(world):
    db, index, ids = world
    seen: list[str] = []
    original = index.embed_query
    index.embed_query = lambda text: (seen.append(text), original(text))[1]  # type: ignore[method-assign]
    with Session(db) as session:
        feed_search.related_items(session, index, "robot")
    assert seen == ["robot"]
