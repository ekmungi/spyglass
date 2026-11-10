# tests/test_rebucket.py
"""Tests for the one-time re-bucket migration.

Publish-day windowing replaced the old fetch-windowed compose_brief. Briefs
composed BEFORE that swap still carry the old covers_from/until window shape (no
publish_day) and may span several distinct local days in one brief -- the very thing
publish-day windowing is meant to prevent. rebucket_recent_briefs resets those RECENT
briefs (un-stamps their cards + deletes the rows) so the next compose_due_briefs pass
rebuilds them into proper per-day briefs (one per publish-day). Older
briefs are left as history.

The guard marker (publish_day_rebucket_done) makes the reset a one-shot: it must run
exactly once, ever, even across many startups.
"""

import re
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlmodel import Session, select

from spyglass_service.brief import compose_due_briefs
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, Item, RunLog
from spyglass_service.rebucket import (
    _rebucket_marker_done,
    _set_rebucket_marker,
    rebucket_recent_briefs,
)

TZ = timezone.utc
TODAY = date(2026, 7, 6)


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


def _day(d: date, hour: int = 12) -> datetime:
    """A naive-UTC datetime at `hour` on local day `d` (tz=UTC so day is exact)."""
    return datetime(d.year, d.month, d.day, hour, 0)


def _add_card(session: Session, ext_id: str, *, published_at: datetime,
              relevance_score: int | None = 85, brief_id: int | None = None) -> Card:
    """Seed one Item + Card pair whose local day is fixed by published_at (tz=UTC)."""
    item = Item(source="test", external_id=ext_id, title=f"Article {ext_id}",
                url=f"https://x.test/{ext_id}", summary="blurb", published_at=published_at)
    session.add(item)
    session.flush()
    card = Card(
        item_id=item.id, summary=f"Summary {ext_id}",
        relevance_score=relevance_score, relevance_at=published_at,
        created_at=published_at, brief_id=brief_id,
    )
    session.add(card)
    session.flush()
    return card


def _seed_brief(session: Session, *, covers_from: datetime, covers_until: datetime,
                 publish_day: str = "") -> Brief:
    """Insert one Brief row (old fetch-windowed shape: publish_day="" by default)."""
    brief = Brief(covers_from=covers_from, covers_until=covers_until,
                  markdown="old body", item_count=1, low_count=0, publish_day=publish_day)
    session.add(brief)
    session.flush()
    return brief


# ---------------------------------------------------------------------------
# rebucket_recent_briefs: reset recent vs preserve old
# ---------------------------------------------------------------------------


def test_recent_brief_is_reset_cards_unstamped_and_row_deleted(tmp_path):
    """A brief whose covers_until falls inside the cutoff window is deleted and its
    stamped cards' brief_id is reset to NULL."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        brief = _seed_brief(s, covers_from=_day(date(2026, 7, 4)), covers_until=_day(date(2026, 7, 5)))
        card = _add_card(s, "recent", published_at=_day(date(2026, 7, 5)), brief_id=brief.id)
        s.commit()
        brief_id, card_id = brief.id, card.id

    deleted = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
    assert deleted == [brief_id]

    with Session(engine) as s:
        assert s.get(Brief, brief_id) is None
        refreshed = s.get(Card, card_id)
        assert refreshed.brief_id is None


def test_old_brief_outside_cutoff_is_untouched(tmp_path):
    """A brief whose covers_until is OLDER than the cutoff is left alone entirely:
    row survives, its cards keep their brief_id."""
    engine = _engine(tmp_path)
    # cutoff = TODAY - 5 days = 2026-07-01; an covers_until well before that is "old".
    with Session(engine) as s:
        brief = _seed_brief(s, covers_from=_day(date(2026, 6, 10)), covers_until=_day(date(2026, 6, 12)))
        card = _add_card(s, "old", published_at=_day(date(2026, 6, 12)), brief_id=brief.id)
        s.commit()
        brief_id, card_id = brief.id, card.id

    deleted = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
    assert deleted == []

    with Session(engine) as s:
        assert s.get(Brief, brief_id) is not None
        refreshed = s.get(Card, card_id)
        assert refreshed.brief_id == brief_id


def test_mixed_recent_and_old_only_recent_is_reset(tmp_path):
    """With both a recent and an old brief present, only the recent one is reset;
    the old one's row and card stamp are untouched. Returns just the recent id."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        old_brief = _seed_brief(s, covers_from=_day(date(2026, 6, 1)), covers_until=_day(date(2026, 6, 2)))
        old_card = _add_card(s, "old", published_at=_day(date(2026, 6, 2)), brief_id=old_brief.id)
        recent_brief = _seed_brief(s, covers_from=_day(date(2026, 7, 5)), covers_until=_day(date(2026, 7, 6)))
        recent_card = _add_card(s, "recent", published_at=_day(date(2026, 7, 6)), brief_id=recent_brief.id)
        s.commit()
        old_brief_id, old_card_id = old_brief.id, old_card.id
        recent_brief_id, recent_card_id = recent_brief.id, recent_card.id

    deleted = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
    assert deleted == [recent_brief_id]

    with Session(engine) as s:
        assert s.get(Brief, old_brief_id) is not None
        assert s.get(Card, old_card_id).brief_id == old_brief_id
        assert s.get(Brief, recent_brief_id) is None
        assert s.get(Card, recent_card_id).brief_id is None


def test_cutoff_boundary_is_inclusive(tmp_path):
    """A brief whose covers_until is EXACTLY at the cutoff boundary is treated as
    recent (>= cutoff), matching the brief's stated inclusive rule."""
    engine = _engine(tmp_path)
    cutoff_day = TODAY - timedelta(days=5)  # 2026-07-01
    with Session(engine) as s:
        brief = _seed_brief(s, covers_from=_day(cutoff_day), covers_until=_day(cutoff_day))
        _add_card(s, "boundary", published_at=_day(cutoff_day), brief_id=brief.id)
        s.commit()
        brief_id = brief.id

    deleted = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
    assert deleted == [brief_id]
    with Session(engine) as s:
        assert s.get(Brief, brief_id) is None


def test_no_briefs_returns_empty_list(tmp_path):
    """An empty DB (nothing to reset) returns an empty list -- a no-op, not an error."""
    engine = _engine(tmp_path)
    assert rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5) == []


# ---------------------------------------------------------------------------
# Marker guard: runs once
# ---------------------------------------------------------------------------


def test_marker_not_done_before_first_run(tmp_path):
    """Before the marker is ever set, the guard reports not-done."""
    engine = _engine(tmp_path)
    assert _rebucket_marker_done(engine) is False


def test_marker_done_after_set(tmp_path):
    """After _set_rebucket_marker, the guard reports done."""
    engine = _engine(tmp_path)
    _set_rebucket_marker(engine)
    assert _rebucket_marker_done(engine) is True


def test_guarded_second_run_is_a_noop(tmp_path):
    """Simulating the startup guard twice: the first pass resets + sets the marker;
    the second pass, guarded, must NOT reset again -- a brief re-seeded after the
    first pass (mimicking a rebuild) survives the second guarded call untouched."""
    engine = _engine(tmp_path)

    def _guarded_pass() -> list[int]:
        if _rebucket_marker_done(engine):
            return []
        result = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
        _set_rebucket_marker(engine)
        return result

    with Session(engine) as s:
        brief = _seed_brief(s, covers_from=_day(date(2026, 7, 5)), covers_until=_day(date(2026, 7, 6)))
        _add_card(s, "first", published_at=_day(date(2026, 7, 6)), brief_id=brief.id)
        s.commit()
        brief_id = brief.id  # captured before the session closes; the row is deleted below

    first = _guarded_pass()
    assert first == [brief_id]
    assert _rebucket_marker_done(engine) is True

    # Re-seed a NEW recent brief post-first-pass (as if compose_due_briefs rebuilt one);
    # the second guarded call must leave it alone entirely.
    with Session(engine) as s:
        rebuilt = _seed_brief(s, covers_from=_day(date(2026, 7, 6)), covers_until=_day(date(2026, 7, 6)))
        rebuilt_card = _add_card(s, "second", published_at=_day(date(2026, 7, 6)), brief_id=rebuilt.id)
        s.commit()
        rebuilt_id, rebuilt_card_id = rebuilt.id, rebuilt_card.id

    second = _guarded_pass()
    assert second == []  # no-op: guard short-circuits before touching anything
    with Session(engine) as s:
        assert s.get(Brief, rebuilt_id) is not None
        assert s.get(Card, rebuilt_card_id).brief_id == rebuilt_id


def test_marker_uses_runlog_source_and_does_not_collide_with_other_markers(tmp_path):
    """The marker is a RunLog row (the codebase's established one-shot pattern, e.g.
    categories.migrate_categories_once) with a dedicated source string, so it can't be
    mistaken for -- or clobbered by -- an unrelated one-time marker."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        s.add(RunLog(source="category_migrate_v1", status="ok"))
        s.commit()
    assert _rebucket_marker_done(engine) is False  # unrelated marker doesn't count
    _set_rebucket_marker(engine)
    with Session(engine) as s:
        sources = {row.source for row in s.exec(select(RunLog)).all()}
    assert "publish_day_rebucket_done" in sources
    assert "category_migrate_v1" in sources  # untouched, both coexist


# ---------------------------------------------------------------------------
# End-to-end: the monster brief splits into one per-day brief per day (no digest)
# ---------------------------------------------------------------------------


def _canned_llm(*, lead: str = "The day at a glance."):
    """LLM stub that satisfies the partition gate for ANY featured-count bucket."""
    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        user = next(m["content"] for m in messages if m["role"] == "user")
        tokens = sorted(set(int(n) for n in re.findall(r"\[#(\d+)\]", user)))
        bullets = [f"Story about [#{n}]." for n in tokens]
        return {"lead": lead, "sections": [{"heading": "Today", "bullets": bullets}]}

    return llm, calls


def test_monster_brief_splits_into_per_day_briefs_on_rebucket_then_compose(tmp_path):
    """The migration's whole point: a pre-publish-day-windowing 'monster' brief whose
    stamped cards span 6 distinct recent local days is reset by rebucket_recent_briefs,
    then compose_due_briefs rebuilds it into exactly 6 per-day briefs (one per day, no
    folded digest) with every card re-stamped."""
    engine = _engine(tmp_path)
    days = [date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2),
            date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)]
    with Session(engine) as s:
        # One old-shape monster brief covering the whole span, publish_day="".
        monster = _seed_brief(
            s, covers_from=_day(days[0]), covers_until=_day(days[-1]), publish_day="",
        )
        for d in days:
            _add_card(s, f"c{d.isoformat()}", published_at=_day(d), relevance_score=85,
                      brief_id=monster.id)
        s.commit()
        monster_id = monster.id

    # --- the migration: guarded reset, then the normal compose trigger ---
    assert _rebucket_marker_done(engine) is False
    deleted = rebucket_recent_briefs(engine, today=TODAY, cutoff_days=5)
    _set_rebucket_marker(engine)
    assert deleted == [monster_id]

    with Session(engine) as s:
        assert s.get(Brief, monster_id) is None  # the monster is gone
        unstamped = [c for c in s.exec(select(Card)).all() if c.brief_id is None]
    assert len(unstamped) == 6  # every card un-stamped, ready to be re-bucketed

    llm, calls = _canned_llm()
    briefs = compose_due_briefs(engine, _index(), _settings(tmp_path), tz=TZ, today=TODAY, llm=llm)

    assert len(briefs) == 6  # one brief per day, never the single monster or a folded digest
    publish_days = [b.publish_day for b in briefs]
    assert publish_days == ["2026-07-05", "2026-07-04", "2026-07-03",
                            "2026-07-02", "2026-07-01", "2026-06-30"]
    for b in briefs:
        assert b.item_count == 1  # each rebuilt brief covers exactly its one day

    with Session(engine) as s:
        still_unstamped = [c for c in s.exec(select(Card)).all() if c.brief_id is None]
    assert still_unstamped == []  # every card re-stamped by its new per-day brief

    # The guard is now set; a second guarded call must not disturb the rebuilt briefs.
    assert _rebucket_marker_done(engine) is True
