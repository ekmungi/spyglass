# tests/test_brief.py
"""Tests for recompose_brief: rebuild an existing brief's narrative in place.

Membership is already decided by the compose pass (Card.brief_id); recompose only
recomputes the featured/listed split and the markdown from the CURRENT effective
relevance, on the same row, never touching covers_* or the stamped membership.

The publish-day compose path (compose_due_briefs) and the window-free
eligibility + bucketing primitives live in tests/test_compose_due_briefs.py and
tests/test_brief_time.py; the old covers_from/until window machinery (resolve_window,
eligible_cards, the 24h default / 72h cap / 20h guard) was removed,
so its tests are gone with it.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, CardState, Item

# Fixed clock: cards are published "yesterday" (Jul 5) so they land on a single,
# un-briefed local day that compose_due_briefs turns into exactly one brief to recompose.
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
DAY = datetime(2026, 7, 5, 12, 0)  # naive-UTC publish day for every seeded card


def _engine(tmp_path):
    """Fresh migrated engine in the test temp dir."""
    engine = create_db_engine(tmp_path / "brief.db")
    init_db(engine)
    return engine


def _index():
    """Empty fake EmbeddingIndex (no vectors -> knn term is zero everywhere)."""
    return EmbeddingIndex(lambda t: np.ones((len(t), 4), dtype=np.float32), "fake", 4)


def _settings(tmp_path):
    """Test Settings; the LLM is always injected so the API key is never needed."""
    from spyglass_service.config import Settings

    return Settings(_env_file=None, data_dir=tmp_path / "data")


def _canned_llm(*, lead: str = "The day at a glance."):
    """LLM stub satisfying the partition gate for any featured-count bucket.

    Emits one bullet per [#n] token found in the USER message (the featured blocks),
    so every featured card is cited exactly once. The system prompt's example tokens
    are ignored (only the user message lists the real featured set).
    """
    import re

    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        user = next(m["content"] for m in messages if m["role"] == "user")
        tokens = sorted({int(n) for n in re.findall(r"\[#(\d+)\]", user)})
        bullets = [f"Story about [#{n}]." for n in tokens]
        return {"lead": lead, "sections": [{"heading": "Today", "bullets": bullets}]}

    return llm, calls


def _add_card(
    session: Session,
    ext_id: str,
    *,
    published_at: datetime = DAY,
    relevance_score: int | None = None,
    judged: bool = True,
    state: CardState = CardState.NEW,
    brief_id: int | None = None,
) -> Card:
    """Seed one Item + Card pair whose local day is fixed by published_at (production tz)."""
    item = Item(source="test", external_id=ext_id, title=f"Article {ext_id}",
                url=f"https://x.test/{ext_id}", summary="blurb", published_at=published_at)
    session.add(item)
    session.flush()
    card = Card(
        item_id=item.id, state=state, summary=f"Summary {ext_id}",
        relevance_score=relevance_score,
        relevance_at=published_at if judged else None,
        created_at=published_at, brief_id=brief_id,
    )
    session.add(card)
    session.flush()
    return card


def _seed_many_featured(session: Session, *, high: int, medium: int) -> None:
    """Seed `high` high-relevance + `medium` medium-relevance cards on the same day.

    Titles are zero-padded so string sort matches creation order; each card is one
    minute apart (newest = index 0) to mirror the created_at desc query ordering.
    """
    for i in range(high):
        _add_card(session, f"high{i:03d}", published_at=DAY - timedelta(minutes=i),
                  relevance_score=85)
    for i in range(medium):
        _add_card(session, f"med{i:03d}", published_at=DAY - timedelta(minutes=high + i),
                  relevance_score=55)


def _compose_one(engine, tmp_path, llm):
    """Compose the single un-briefed day (Jul 5) and return the one resulting Brief."""
    from spyglass_service.brief import compose_due_briefs

    briefs = compose_due_briefs(engine, _index(), _settings(tmp_path), now=NOW, llm=llm)
    assert len(briefs) == 1  # every card is on the same day -> exactly one brief
    return briefs[0]


# ---------------------------------------------------------------------------
# recompose_brief: rebuild an existing brief in place
# ---------------------------------------------------------------------------


def _composed_brief(engine, tmp_path):
    """Compose one brief over 2 featured + 1 low card; returns (brief, card ids by ext_id)."""
    ids: dict[str, int] = {}
    with Session(engine) as s:
        ids["one"] = _add_card(s, "one", relevance_score=85).id
        ids["two"] = _add_card(s, "two", relevance_score=55).id
        ids["low"] = _add_card(s, "low", relevance_score=25).id
        s.commit()
    llm, _ = _canned_llm()
    brief = _compose_one(engine, tmp_path, llm)
    return brief, ids


def test_recompose_overwrites_in_place_and_keeps_membership(tmp_path):
    """Recompose rewrites markdown/item_count/low_count on the SAME row from the SAME
    stamped cards -- a card demoted since compose moves to the tail, a new un-stamped
    card never joins, and covers_* stay put."""
    from spyglass_service.brief import recompose_brief

    engine = _engine(tmp_path)
    brief, ids = _composed_brief(engine, tmp_path)
    with Session(engine) as s:
        # Demote 'two' below the featured bar; its membership must not change.
        demoted = s.get(Card, ids["two"])
        demoted.relevance_score = 20
        s.add(demoted)
        # A new eligible-looking card that arrived AFTER compose: membership is already
        # decided, so recompose must ignore it.
        _add_card(s, "latecomer", relevance_score=90)
        s.commit()
    llm, calls = _canned_llm(lead="A fresh look.")
    out = recompose_brief(engine, _index(), _settings(tmp_path), brief.id, llm=llm)
    assert out.id == brief.id and calls["n"] == 1
    assert "A fresh look." in out.markdown
    assert out.item_count == 1 and out.low_count == 2  # 'two' joined the tail
    assert out.covers_from == brief.covers_from and out.covers_until == brief.covers_until
    with Session(engine) as s:
        stamped = {c.id for c in s.exec(select(Card)).all() if c.brief_id == brief.id}
    assert stamped == set(ids.values())  # exactly the original membership
    assert "latecomer" not in out.markdown


def test_recompose_ignores_the_feed_disabled_filter(tmp_path):
    """A stamped card whose feed was disabled AFTER compose stays in the brief --
    membership is already decided, the display filter does not apply here."""
    from spyglass_service.brief import recompose_brief
    from spyglass_service.models import Feed

    engine = _engine(tmp_path)
    with Session(engine) as s:
        card = _add_card(s, "feedy", relevance_score=85)
        item = s.get(Item, card.item_id)
        item.feed_url = "https://x.test/feed.xml"
        s.add(item)
        s.add(Feed(feed_url="https://x.test/feed.xml", name="X", kind="rss",
                   enabled=True, added_via="manual"))
        s.commit()
    llm, _ = _canned_llm()
    brief = _compose_one(engine, tmp_path, llm)
    with Session(engine) as s:
        feed = s.exec(select(Feed)).one()
        feed.enabled = False
        s.add(feed)
        s.commit()
    llm2, _ = _canned_llm()
    out = recompose_brief(engine, _index(), _settings(tmp_path), brief.id, llm=llm2)
    assert out.item_count == 1
    assert "Article feedy" in out.markdown


def test_recompose_unknown_brief_returns_none(tmp_path):
    """An unknown brief id is None (the API layer turns that into a 404)."""
    from spyglass_service.brief import recompose_brief

    engine = _engine(tmp_path)
    assert recompose_brief(engine, _index(), _settings(tmp_path), 9999) is None


def test_recompose_llm_failure_leaves_the_brief_untouched(tmp_path):
    """An LLM failure during recompose raises BriefComposeError and changes nothing."""
    import pytest

    from spyglass_service.brief import BriefComposeError, recompose_brief

    engine = _engine(tmp_path)
    brief, _ids = _composed_brief(engine, tmp_path)

    def boom(messages):
        raise RuntimeError("OpenRouter down")

    with pytest.raises(BriefComposeError):
        recompose_brief(engine, _index(), _settings(tmp_path), brief.id, llm=boom)
    with Session(engine) as s:
        stored = s.get(Brief, brief.id)
        assert stored.markdown == brief.markdown  # in-place overwrite never happened
        assert stored.item_count == brief.item_count


def test_recompose_listed_only_path_needs_no_llm(tmp_path):
    """When every stamped card is now below the bar, recompose uses the fixed lead
    with zero sections and never calls the LLM."""
    from spyglass_service.brief import recompose_brief
    from spyglass_service.brief_narrative import NO_FEATURED_LEAD

    engine = _engine(tmp_path)
    brief, ids = _composed_brief(engine, tmp_path)
    with Session(engine) as s:
        for cid in (ids["one"], ids["two"]):
            card = s.get(Card, cid)
            card.relevance_score = 10
            s.add(card)
        s.commit()
    llm, calls = _canned_llm()
    out = recompose_brief(engine, _index(), _settings(tmp_path), brief.id, llm=llm)
    assert calls["n"] == 0
    assert out.markdown.startswith(NO_FEATURED_LEAD)
    assert out.item_count == 0 and out.low_count == 3


def test_recompose_brief_caps_featured_and_does_not_bypass_on_recompose(tmp_path):
    """A brief stamped with > FEATURED_CAP medium/high cards is recomposed: the cap still
    applies (exactly CAP featured + remainder listed), proving recompose cannot silently
    un-cap a large brief back to its full featured set."""
    from spyglass_service.brief import FEATURED_CAP, recompose_brief

    engine = _engine(tmp_path)
    total = FEATURED_CAP + 7
    with Session(engine) as s:
        _seed_many_featured(s, high=0, medium=total)
        s.commit()
    llm, _ = _canned_llm()
    brief = _compose_one(engine, tmp_path, llm)
    assert brief.item_count == FEATURED_CAP
    assert brief.low_count == 7

    # Recompose over the same stamped membership: still capped, not bypassed.
    llm2, _ = _canned_llm()
    out = recompose_brief(engine, _index(), _settings(tmp_path), brief.id, llm=llm2)
    assert out is not None
    assert out.item_count == FEATURED_CAP
    assert out.low_count == 7
