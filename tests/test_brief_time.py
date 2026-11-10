# tests/test_brief_time.py
"""Tests for the local_day windowing helper and the
window-free eligibility + publish-day bucketing pure functions."""

from datetime import UTC, date, datetime, timedelta, timezone

import numpy as np
from sqlmodel import Session

from spyglass_service.brief_time import (
    briefed_days,
    days_to_compose,
    eligible_pairs,
    local_day,
)
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, CardState, Item

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def _item(published_at: datetime | None) -> Item:
    """Build a minimal Item with the given published_at (unsaved, no id needed)."""
    return Item(source="t", external_id="x", title="T", url="https://x.test", published_at=published_at)


def _card(created_at: datetime) -> Card:
    """Build a minimal Card with the given created_at (unsaved, no id needed)."""
    return Card(item_id=1, summary="s", created_at=created_at)


def _engine(tmp_path):
    """Fresh migrated engine in the test temp dir (mirrors tests/test_brief.py)."""
    engine = create_db_engine(tmp_path / "brief_time.db")
    init_db(engine)
    return engine


def _index():
    """Empty fake EmbeddingIndex (no vectors -> knn term is zero everywhere)."""
    return EmbeddingIndex(lambda t: np.ones((len(t), 4), dtype=np.float32), "fake", 4)


def _add_card(
    session: Session,
    ext_id: str,
    *,
    created_at: datetime,
    relevance_score: int | None = None,
    judged: bool = True,
    state: CardState = CardState.NEW,
    brief_id: int | None = None,
    published_at: datetime | None = None,
) -> Card:
    """Seed one Item + Card pair with controlled created_at/published_at and relevance
    (mirrors tests/test_brief.py's helper of the same name, + published_at for day tests)."""
    item = Item(source="test", external_id=ext_id, title=f"Article {ext_id}",
                url=f"https://x.test/{ext_id}", summary="blurb", published_at=published_at)
    session.add(item)
    session.flush()
    card = Card(
        item_id=item.id, state=state, summary=f"Summary {ext_id}",
        relevance_score=relevance_score,
        relevance_at=created_at if judged else None,
        created_at=created_at, brief_id=brief_id,
    )
    session.add(card)
    session.flush()
    return card


def test_local_day_rolls_forward_across_midnight_for_positive_offset_tz():
    """23:30 UTC in UTC+2 lands on the NEXT local day."""
    published = datetime(2026, 7, 5, 23, 30, tzinfo=UTC)
    item = _item(published)
    card = _card(datetime(2026, 7, 5, 23, 30, tzinfo=UTC))
    tz = timezone(timedelta(hours=2))

    result = local_day(card, item, tz=tz, today=date(2026, 7, 10))

    assert result == date(2026, 7, 6)


def test_local_day_rolls_backward_across_midnight_for_negative_offset_tz():
    """02:00 UTC in UTC-8 lands on the PREVIOUS local day."""
    published = datetime(2026, 7, 5, 2, 0, tzinfo=UTC)
    item = _item(published)
    card = _card(datetime(2026, 7, 5, 2, 0, tzinfo=UTC))
    tz = timezone(timedelta(hours=-8))

    result = local_day(card, item, tz=tz, today=date(2026, 7, 10))

    assert result == date(2026, 7, 4)


def test_local_day_falls_back_to_card_created_at_when_published_at_is_none():
    """A missing published_at (e.g. non-RSS sources) falls back to the card's created_at."""
    item = _item(None)
    card = _card(datetime(2026, 7, 5, 12, 0, tzinfo=UTC))
    tz = timezone(timedelta(hours=0))

    result = local_day(card, item, tz=tz, today=date(2026, 7, 10))

    assert result == date(2026, 7, 5)


def test_local_day_clamps_a_future_local_day_to_today():
    """A published_at whose local day is after 'today' clamps to today (no future-dated cards)."""
    published = datetime(2026, 7, 10, 23, 0, tzinfo=UTC)
    item = _item(published)
    card = _card(published)
    tz = timezone(timedelta(hours=5))  # local day would be 2026-07-11

    result = local_day(card, item, tz=tz, today=date(2026, 7, 10))

    assert result == date(2026, 7, 10)


def test_local_day_normal_mid_day_date_is_unchanged():
    """A normal mid-day UTC timestamp with a neutral tz stays on the same calendar day."""
    published = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    item = _item(published)
    card = _card(published)
    tz = timezone(timedelta(hours=0))

    result = local_day(card, item, tz=tz, today=date(2026, 7, 10))

    assert result == date(2026, 7, 5)


# ---------------------------------------------------------------------------
# eligible_pairs: window-free eligibility -- un-briefed, non-dismissed cards split into
# featured/listed by effective relevance, with no created_at bounds.
# ---------------------------------------------------------------------------


def test_eligible_pairs_split_featured_vs_listed_by_effective_level(tmp_path):
    """Medium/high effective relevance is featured; low is listed; out is excluded --
    same split behavior as eligible_cards, just without a window."""
    engine = _engine(tmp_path)
    inside = NOW - timedelta(hours=2)
    with Session(engine) as s:
        _add_card(s, "high", created_at=inside, relevance_score=85)
        _add_card(s, "medium", created_at=inside, relevance_score=55)
        _add_card(s, "low", created_at=inside, relevance_score=25)
        _add_card(s, "out", created_at=inside, relevance_score=5)
        s.commit()
    featured, listed = eligible_pairs(engine, _index())
    featured_titles = {item.title for _card, item in featured}
    listed_titles = {item.title for _card, item in listed}
    assert featured_titles == {"Article high", "Article medium"}
    assert listed_titles == {"Article low"}


def test_eligible_pairs_exclude_unjudged_briefed_and_dismissed(tmp_path):
    """Unjudged, already-briefed, and dismissed cards never qualify (same exclusions
    as eligible_cards)."""
    engine = _engine(tmp_path)
    inside = NOW - timedelta(hours=2)
    with Session(engine) as s:
        s.add(Brief(covers_from=NOW - timedelta(hours=48), covers_until=NOW - timedelta(hours=24),
                    markdown="prev", item_count=1, low_count=0))
        s.flush()
        _add_card(s, "unjudged", created_at=inside, relevance_score=None, judged=False)
        _add_card(s, "briefed", created_at=inside, relevance_score=85, brief_id=1)
        _add_card(s, "dismissed", created_at=inside, relevance_score=85, state=CardState.DISMISSED)
        _add_card(s, "keeper", created_at=inside, relevance_score=85)
        s.commit()
    featured, listed = eligible_pairs(engine, _index())
    assert [item.title for _card, item in featured] == ["Article keeper"]
    assert listed == []


def test_eligible_pairs_has_no_date_window_effect(tmp_path):
    """A very old un-briefed card is still eligible -- there is no created_at bound at all,
    unlike eligible_cards which excludes anything outside (covers_from, covers_until]."""
    engine = _engine(tmp_path)
    very_old = NOW - timedelta(days=365)
    with Session(engine) as s:
        _add_card(s, "ancient", created_at=very_old, relevance_score=85)
        s.commit()
    featured, _listed = eligible_pairs(engine, _index())
    assert [item.title for _card, item in featured] == ["Article ancient"]


# ---------------------------------------------------------------------------
# briefed_days: local days already claimed by any existing brief.
# ---------------------------------------------------------------------------


def test_briefed_days_single_day_brief_claims_one_day(tmp_path):
    """A brief whose only stamped card falls on one local day claims exactly that day."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    published = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        brief = Brief(covers_from=published - timedelta(hours=1), covers_until=published + timedelta(hours=1),
                       markdown="m", item_count=1, low_count=0)
        s.add(brief)
        s.flush()
        _add_card(s, "one", created_at=published, published_at=published, brief_id=brief.id)
        s.commit()
    days = briefed_days(engine, tz=tz, today=date(2026, 7, 10))
    assert days == {date(2026, 7, 1)}


def test_briefed_days_digest_span_claims_every_day_even_without_a_card(tmp_path):
    """A digest brief's covers_from..covers_until span claims its FULL day range, even for
    days inside the span that have no stamped card at all -- so a late item for a gap day
    doesn't spin off a stray brief."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    covers_from = datetime(2026, 6, 28, 0, 0, tzinfo=UTC)
    covers_until = datetime(2026, 7, 1, 23, 59, tzinfo=UTC)
    with Session(engine) as s:
        brief = Brief(covers_from=covers_from, covers_until=covers_until,
                       markdown="digest", item_count=2, low_count=0)
        s.add(brief)
        s.flush()
        # Cards only on 2 of the 4 days the span covers (6/28 and 7/1).
        _add_card(s, "a", created_at=covers_from, published_at=covers_from, brief_id=brief.id)
        _add_card(s, "b", created_at=covers_until, published_at=covers_until, brief_id=brief.id)
        s.commit()
    days = briefed_days(engine, tz=tz, today=date(2026, 7, 10))
    assert days == {date(2026, 6, 28), date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)}


def test_briefed_days_respects_timezone(tmp_path):
    """A card's local day shifts with tz, same rule as local_day."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=-8))
    published = datetime(2026, 7, 5, 2, 0, tzinfo=UTC)  # local day: 7/4 in UTC-8
    with Session(engine) as s:
        brief = Brief(covers_from=published, covers_until=published, markdown="m",
                       item_count=1, low_count=0)
        s.add(brief)
        s.flush()
        _add_card(s, "one", created_at=published, published_at=published, brief_id=brief.id)
        s.commit()
    days = briefed_days(engine, tz=tz, today=date(2026, 7, 10))
    assert date(2026, 7, 4) in days


def test_briefed_days_union_across_multiple_briefs(tmp_path):
    """Days claimed by different briefs are all unioned together."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    day1 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    day2 = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        b1 = Brief(covers_from=day1, covers_until=day1, markdown="m1", item_count=1, low_count=0)
        b2 = Brief(covers_from=day2, covers_until=day2, markdown="m2", item_count=1, low_count=0)
        s.add(b1)
        s.add(b2)
        s.flush()
        _add_card(s, "one", created_at=day1, published_at=day1, brief_id=b1.id)
        _add_card(s, "two", created_at=day2, published_at=day2, brief_id=b2.id)
        s.commit()
    days = briefed_days(engine, tz=tz, today=date(2026, 7, 10))
    assert days == {date(2026, 7, 1), date(2026, 7, 2)}


def test_briefed_days_empty_when_no_briefs_exist(tmp_path):
    """No briefs at all -> the empty set."""
    engine = _engine(tmp_path)
    assert briefed_days(engine, today=date(2026, 7, 10)) == set()


# ---------------------------------------------------------------------------
# days_to_compose: distinct eligible local days minus briefed_days,
# sorted descending (newest first).
# ---------------------------------------------------------------------------


def test_days_to_compose_excludes_already_briefed_days(tmp_path):
    """Eligible cards across 3 days, one of which is already briefed -> that day excluded."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    d1 = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    d2 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    d3 = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        # d2 is already briefed via a stamped card on that day.
        brief = Brief(covers_from=d2, covers_until=d2, markdown="m", item_count=1, low_count=0)
        s.add(brief)
        s.flush()
        _add_card(s, "briefed-day", created_at=d2, published_at=d2, brief_id=brief.id, relevance_score=85)
        # Eligible (un-briefed) cards on d1, d2 (different card), and d3.
        _add_card(s, "one", created_at=d1, published_at=d1, relevance_score=85)
        _add_card(s, "two", created_at=d2, published_at=d2, relevance_score=85)
        _add_card(s, "three", created_at=d3, published_at=d3, relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=date(2026, 7, 10))
    assert days == [date(2026, 7, 2), date(2026, 6, 30)]  # d2 (7/1) excluded, newest first


def test_days_to_compose_sorted_newest_first(tmp_path):
    """Result is sorted descending regardless of insertion order."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    d1 = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    d2 = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    d3 = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        _add_card(s, "a", created_at=d1, published_at=d1, relevance_score=85)
        _add_card(s, "b", created_at=d2, published_at=d2, relevance_score=85)
        _add_card(s, "c", created_at=d3, published_at=d3, relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=date(2026, 7, 10))
    assert days == [date(2026, 7, 3), date(2026, 6, 30), date(2026, 6, 28)]


def test_days_to_compose_dateless_card_falls_into_created_at_day(tmp_path):
    """A card with no item.published_at falls back to its created_at day (local_day rule)."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    created = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        _add_card(s, "nopublish", created_at=created, published_at=None, relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=date(2026, 7, 10))
    assert days == [date(2026, 7, 1)]


def test_days_to_compose_empty_when_nothing_eligible(tmp_path):
    """No eligible cards at all -> an empty list."""
    engine = _engine(tmp_path)
    assert days_to_compose(engine, _index(), today=date(2026, 7, 10)) == []


# ---------------------------------------------------------------------------
# days_to_compose horizon_days: bounds eligibility
# to publish-days within the last N days so a long never-briefed backlog can't flood a
# run with one brief per old day. Filters on local_day (not created_at) -- robust to
# coarse/wrong published_at and directly bounds which publish-days get a brief.
# ---------------------------------------------------------------------------


def test_days_to_compose_horizon_excludes_a_day_older_than_the_horizon(tmp_path):
    """A card whose local_day is 20 days before today is excluded when horizon_days=14."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    today = date(2026, 7, 10)
    old_day = today - timedelta(days=20)
    with Session(engine) as s:
        _add_card(s, "old", created_at=datetime.combine(old_day, datetime.min.time(), tzinfo=UTC),
                   published_at=datetime.combine(old_day, datetime.min.time(), tzinfo=UTC),
                   relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=today, horizon_days=14)
    assert days == []


def test_days_to_compose_horizon_includes_a_day_inside_the_horizon(tmp_path):
    """A card whose local_day is 10 days before today is included when horizon_days=14."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    today = date(2026, 7, 10)
    recent_day = today - timedelta(days=10)
    with Session(engine) as s:
        _add_card(s, "recent", created_at=datetime.combine(recent_day, datetime.min.time(), tzinfo=UTC),
                   published_at=datetime.combine(recent_day, datetime.min.time(), tzinfo=UTC),
                   relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=today, horizon_days=14)
    assert days == [recent_day]


def test_days_to_compose_horizon_boundary_exactly_n_days_is_included(tmp_path):
    """A card exactly horizon_days before today is included (inclusive boundary)."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    today = date(2026, 7, 10)
    boundary_day = today - timedelta(days=14)
    with Session(engine) as s:
        _add_card(s, "boundary", created_at=datetime.combine(boundary_day, datetime.min.time(), tzinfo=UTC),
                   published_at=datetime.combine(boundary_day, datetime.min.time(), tzinfo=UTC),
                   relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=today, horizon_days=14)
    assert days == [boundary_day]


def test_days_to_compose_horizon_none_keeps_unbounded_behavior(tmp_path):
    """horizon_days=None (the default) is a regression guard: no horizon at all, so
    eligibility stays unbounded -- a very old card stays eligible."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    today = date(2026, 7, 10)
    ancient_day = today - timedelta(days=365)
    with Session(engine) as s:
        _add_card(s, "ancient", created_at=datetime.combine(ancient_day, datetime.min.time(), tzinfo=UTC),
                   published_at=datetime.combine(ancient_day, datetime.min.time(), tzinfo=UTC),
                   relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=today)
    assert days == [ancient_day]


def test_days_to_compose_horizon_zero_or_negative_disables_horizon(tmp_path):
    """horizon_days<=0 is the documented escape hatch: unbounded, same as None."""
    engine = _engine(tmp_path)
    tz = timezone(timedelta(hours=0))
    today = date(2026, 7, 10)
    ancient_day = today - timedelta(days=365)
    with Session(engine) as s:
        _add_card(s, "ancient", created_at=datetime.combine(ancient_day, datetime.min.time(), tzinfo=UTC),
                   published_at=datetime.combine(ancient_day, datetime.min.time(), tzinfo=UTC),
                   relevance_score=85)
        s.commit()
    days = days_to_compose(engine, _index(), tz=tz, today=today, horizon_days=0)
    assert days == [ancient_day]
