# tests/test_compose_due_briefs.py
"""Tests for compose_due_briefs: multi-brief publish-day compose.

compose_due_briefs replaces the single-window compose_brief. It composes one brief
per un-briefed local day within the recency horizon (newest first), with no cap on the
number of days and no folded "earlier" digest, gives EACH day its own DB transaction,
and pauses only the failing day -- committed briefs survive an LLM failure in a later
one. The LLM is always injected as a fake so no network call happens.

Determinism: every test pins tz=UTC and today, and seeds each card's published_at on
an exact UTC calendar day so local_day (tz=UTC) maps a card straight to that date.
"""

import re
from datetime import UTC, date, datetime, timedelta, timezone

import numpy as np
from sqlmodel import Session, select

from spyglass_service.brief import compose_due_briefs
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Brief, Card, Item

# Fixed clock for the whole file: "now" is midday on 2026-07-06 UTC, so today = Jul 6.
TZ = timezone.utc
TODAY = date(2026, 7, 6)
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


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
    """LLM stub that satisfies the partition gate for ANY featured-count bucket.

    It reads the [#n] tokens present in the user message (each featured card is one
    block "[#i] Article ...") and emits one bullet per token, so every featured card
    is cited exactly once whether a bucket has 1 card or a multi-day digest has several.
    """
    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        # Only the USER message lists the featured blocks ("[#i] Article ..."); the SYSTEM
        # prompt carries "[#n]" tokens as format examples, so scanning it would invent
        # out-of-range citations. Read the user message alone to get the real featured set.
        user = next(m["content"] for m in messages if m["role"] == "user")
        tokens = sorted(set(int(n) for n in re.findall(r"\[#(\d+)\]", user)))
        bullets = [f"Story about [#{n}]." for n in tokens]
        return {"lead": lead, "sections": [{"heading": "Today", "bullets": bullets}]}

    return llm, calls


def _add_card(
    session: Session,
    ext_id: str,
    *,
    published_at: datetime,
    relevance_score: int | None = 85,
    brief_id: int | None = None,
) -> Card:
    """Seed one Item + Card pair whose local day is fixed by published_at (tz=UTC).

    created_at is set alongside published_at so the newest-first ordering and any
    created_at fallback both agree with the intended day.
    """
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


def _day(d: date, hour: int = 12) -> datetime:
    """A naive-UTC datetime at `hour` on local day `d` (tz=UTC so day is exact)."""
    return datetime(d.year, d.month, d.day, hour, 0)


def _compose(engine, tmp_path, llm):
    """Run compose_due_briefs with the file's fixed tz/today and the given llm."""
    return compose_due_briefs(
        engine, _index(), _settings(tmp_path), now=NOW, tz=TZ, today=TODAY, llm=llm
    )


# ---------------------------------------------------------------------------
# (0) the `now` contract
# ---------------------------------------------------------------------------


def test_now_drives_day_selection_when_today_is_omitted(tmp_path):
    """`now` must select the compose window, not be silently discarded.

    It used to be accepted and thrown away, so a caller passing only `now` got a window
    derived from the real clock instead. That made every such test expire on a timer: the
    seeded day eventually fell outside `brief_horizon_days` and the compose returned
    nothing. Deliberately passes NO `today`, which is the exact shape that broke.
    """
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "one", published_at=_day(date(2026, 7, 5)))
        s.commit()
    llm, _ = _canned_llm()

    briefs = compose_due_briefs(engine, _index(), _settings(tmp_path), now=NOW, tz=TZ, llm=llm)

    # Jul 5 is one day before `now`; only the real clock (years later) puts it out of horizon.
    assert len(briefs) == 1
    assert briefs[0].item_count == 1


def test_explicit_today_still_wins_over_now(tmp_path):
    """`today` stays the authority when both are given -- `now` only fills the gap.

    Pinned so the precedence cannot be quietly inverted: with `today` two months
    after the seeded day, that day is outside the 14-day horizon and nothing composes,
    regardless of what `now` says.
    """
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "one", published_at=_day(date(2026, 7, 5)))
        s.commit()
    llm, calls = _canned_llm()

    briefs = compose_due_briefs(
        engine, _index(), _settings(tmp_path), now=NOW, tz=TZ, today=date(2026, 9, 1), llm=llm
    )

    # The card IS eligible and un-briefed -- only `today` puts its day out of horizon, so an
    # empty result here can only mean `today` won.
    assert briefs == []
    assert calls["n"] == 0  # nothing due -> no LLM call at all


# ---------------------------------------------------------------------------
# (a) steady state: one missing day -> one brief
# ---------------------------------------------------------------------------


def test_steady_one_missing_day_composes_one_brief_and_stamps(tmp_path):
    """A single un-briefed day yields exactly one brief with publish_day set and its
    featured + listed cards stamped."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "feat", published_at=_day(date(2026, 7, 5)), relevance_score=85)
        _add_card(s, "low", published_at=_day(date(2026, 7, 5)), relevance_score=25)
        s.commit()
    llm, calls = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert len(briefs) == 1
    brief = briefs[0]
    assert brief.publish_day == "2026-07-05"
    assert brief.item_count == 1 and brief.low_count == 1
    assert calls["n"] == 1
    with Session(engine) as s:
        stamped = {c.id for c in s.exec(select(Card)).all() if c.brief_id == brief.id}
    assert len(stamped) == 2  # featured + listed both stamped


def test_steady_covers_from_until_span_the_members(tmp_path):
    """covers_from/covers_until are the min/max of the members' publish timestamps."""
    engine = _engine(tmp_path)
    early = _day(date(2026, 7, 5), hour=6)
    late = _day(date(2026, 7, 5), hour=20)
    with Session(engine) as s:
        _add_card(s, "early", published_at=early, relevance_score=85)
        _add_card(s, "late", published_at=late, relevance_score=85)
        s.commit()
    llm, _ = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert len(briefs) == 1
    assert briefs[0].covers_from.replace(tzinfo=None) == early
    assert briefs[0].covers_until.replace(tzinfo=None) == late


# ---------------------------------------------------------------------------
# (b) a 6-day gap -> 6 per-day briefs, one per day, no "earlier" digest
# ---------------------------------------------------------------------------


def test_six_day_gap_yields_one_brief_per_day_no_digest(tmp_path):
    """Six un-briefed days compose SIX individual per-day briefs. There is no cap on
    the number of days and no folded 'earlier' digest, so every un-briefed publish-day within the
    horizon keys its OWN single-day brief (newest-first), and every card is stamped."""
    engine = _engine(tmp_path)
    days = [date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2),
            date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)]
    with Session(engine) as s:
        for d in days:
            _add_card(s, f"c{d.isoformat()}", published_at=_day(d), relevance_score=85)
        s.commit()
    llm, calls = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert len(briefs) == 6
    publish_days = [b.publish_day for b in briefs]
    # Newest-first, one brief per publish-day, no folded "earlier" digest at the tail.
    assert publish_days == ["2026-07-05", "2026-07-04", "2026-07-03",
                            "2026-07-02", "2026-07-01", "2026-06-30"]
    # Every brief is a single-day brief: its covered span never crosses into another day.
    for b in briefs:
        assert b.covers_from.date() == b.covers_until.date()
        assert b.item_count == 1  # each day's one featured card; nothing merged
    # All six cards are stamped by some brief.
    with Session(engine) as s:
        unstamped = [c for c in s.exec(select(Card)).all() if c.brief_id is None]
    assert unstamped == []


# ---------------------------------------------------------------------------
# (c) compose-once: an already-briefed day is not recomposed
# ---------------------------------------------------------------------------


def test_compose_once_briefed_day_not_recomposed_and_straggler_stays(tmp_path):
    """A day already claimed by a brief is not recomposed; a late straggler that lands on
    that same claimed day is left unstamped (it belongs to the already-composed day)."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        # An existing brief that already claims Jul 5 (one stamped card + its span).
        brief = Brief(covers_from=_day(date(2026, 7, 5), hour=8),
                      covers_until=_day(date(2026, 7, 5), hour=8),
                      markdown="old", item_count=1, low_count=0, publish_day="2026-07-05")
        s.add(brief)
        s.flush()
        _add_card(s, "already", published_at=_day(date(2026, 7, 5), hour=8),
                  relevance_score=85, brief_id=brief.id)
        # A late straggler for the SAME (claimed) day -- must stay unstamped.
        _add_card(s, "straggler", published_at=_day(date(2026, 7, 5), hour=22), relevance_score=85)
        s.commit()
    llm, calls = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert briefs == []  # nothing new to compose; Jul 5 already claimed
    assert calls["n"] == 0
    with Session(engine) as s:
        straggler = s.exec(select(Card).where(Card.summary == "Summary straggler")).one()
    assert straggler.brief_id is None  # still eligible, never pulled into the claimed day


# ---------------------------------------------------------------------------
# (d) per-bucket pause: one bucket's LLM raises -> only that bucket is unwritten
# ---------------------------------------------------------------------------


def test_per_bucket_pause_isolates_the_failing_bucket(tmp_path):
    """When the LLM raises for exactly one day's featured set, that bucket is rolled back
    (no brief, its cards stay eligible) while the OTHER buckets commit normally."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "good5", published_at=_day(date(2026, 7, 5)), relevance_score=85)
        _add_card(s, "bad4", published_at=_day(date(2026, 7, 4)), relevance_score=85)
        _add_card(s, "good3", published_at=_day(date(2026, 7, 3)), relevance_score=85)
        s.commit()

    # The fake LLM raises only for the Jul-4 bucket (identified by its featured block text).
    def llm(messages):
        blob = " ".join(m["content"] for m in messages)
        if "Article bad4" in blob:
            raise RuntimeError("OpenRouter down for this bucket")
        return {"lead": "L", "sections": [{"heading": "Today", "bullets": ["Story [#1]."]}]}

    briefs = _compose(engine, tmp_path, llm)
    # Two buckets committed (Jul 5, Jul 3); the Jul-4 bucket paused.
    assert [b.publish_day for b in briefs] == ["2026-07-05", "2026-07-03"]
    with Session(engine) as s:
        cards = {c.summary: c for c in s.exec(select(Card)).all()}
    assert cards["Summary good5"].brief_id is not None
    assert cards["Summary good3"].brief_id is not None
    assert cards["Summary bad4"].brief_id is None  # paused bucket -> still eligible for retry


def test_per_bucket_pause_leaves_no_brief_row_for_failed_bucket(tmp_path):
    """The paused bucket writes NO Brief row at all (never a partial/degraded brief)."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "bad5", published_at=_day(date(2026, 7, 5)), relevance_score=85)
        _add_card(s, "good4", published_at=_day(date(2026, 7, 4)), relevance_score=85)
        s.commit()

    def llm(messages):
        blob = " ".join(m["content"] for m in messages)
        if "Article bad5" in blob:
            raise RuntimeError("down")
        return {"lead": "L", "sections": [{"heading": "Today", "bullets": ["Story [#1]."]}]}

    briefs = _compose(engine, tmp_path, llm)
    assert [b.publish_day for b in briefs] == ["2026-07-04"]
    with Session(engine) as s:
        publish_days = {b.publish_day for b in s.exec(select(Brief)).all()}
    assert publish_days == {"2026-07-04"}  # only the good bucket persisted a row


# ---------------------------------------------------------------------------
# (e) empty: nothing eligible -> no briefs, no LLM call
# ---------------------------------------------------------------------------


def test_empty_when_no_eligible_days(tmp_path):
    """No eligible cards -> an empty list and no LLM call."""
    engine = _engine(tmp_path)
    llm, calls = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert briefs == []
    assert calls["n"] == 0


def test_listed_only_day_composes_without_llm(tmp_path):
    """A day with only low cards still composes (Also noticed) and calls no LLM."""
    engine = _engine(tmp_path)
    with Session(engine) as s:
        _add_card(s, "low", published_at=_day(date(2026, 7, 5)), relevance_score=25)
        s.commit()
    llm, calls = _canned_llm()
    briefs = _compose(engine, tmp_path, llm)
    assert len(briefs) == 1
    assert briefs[0].item_count == 0 and briefs[0].low_count == 1
    assert briefs[0].publish_day == "2026-07-05"
    assert calls["n"] == 0  # nothing featured -> no narrative to write


# ---------------------------------------------------------------------------
# (f) recency horizon end-to-end: a seeded corpus
# spanning 30 publish-days with settings.brief_horizon_days=14 composes ONE brief per
# in-horizon day (no cap on the number of days, so no digest); older never-briefed
# cards stay unstamped (deferred, not dropped).
# ---------------------------------------------------------------------------


def test_horizon_only_composes_days_within_settings_brief_horizon_days(tmp_path):
    """30 publish-days back from today, horizon_days=14 (via settings): every day within
    the last 14 days (today .. today-14 = 15 days) composes its OWN brief; cards on days
    older than the horizon are never stamped -- they stay eligible (unbriefed), not
    dropped -- and no 'earlier' digest is produced."""
    engine = _engine(tmp_path)
    days = [TODAY - timedelta(days=i) for i in range(30)]  # 0..29 days back from TODAY
    with Session(engine) as s:
        for d in days:
            _add_card(s, f"c{d.isoformat()}", published_at=_day(d), relevance_score=85)
        s.commit()

    settings = _settings(tmp_path)
    settings.brief_horizon_days = 14
    llm, calls = _canned_llm()
    briefs = compose_due_briefs(engine, _index(), settings, now=NOW, tz=TZ, today=TODAY, llm=llm)

    in_horizon = {d for d in days if d >= TODAY - timedelta(days=14)}
    out_of_horizon = {d for d in days if d < TODAY - timedelta(days=14)}
    # One brief per in-horizon day (15 days: today .. today-14), no folded digest.
    assert len(briefs) == len(in_horizon) == 15
    covered_days = {b.publish_day for b in briefs}
    assert covered_days == {d.isoformat() for d in in_horizon}

    with Session(engine) as s:
        cards = {c.summary: c for c in s.exec(select(Card)).all()}
    # Every out-of-horizon card is unstamped (deferred, not dropped).
    for d in out_of_horizon:
        assert cards[f"Summary c{d.isoformat()}"].brief_id is None
    # Every in-horizon card is stamped by its own day's brief.
    for d in in_horizon:
        assert cards[f"Summary c{d.isoformat()}"].brief_id is not None
