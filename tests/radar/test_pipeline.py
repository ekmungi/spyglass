"""Tests for the assessment pipeline and the from-user backfill."""

from datetime import timedelta

import pytest
from sqlmodel import Session, select

from spyglass_service.radar import pipeline
from spyglass_service.radar.models import Assessment, ItemState
from spyglass_service.radar.pipeline import backfill_from_user, run_pipeline

from .test_assess_support import (
    BASE_TIME,
    FakeLlm,
    add_feed,
    add_inbox_entry,
    add_item,
    make_engine,
    make_settings,
    set_state,
    store_text,
    utc,
)


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _assessments(engine) -> dict[int, Assessment]:
    """Every stored assessment by item id."""
    with Session(engine) as session:
        return {a.item_id: a for a in session.exec(select(Assessment)).all()}


def _no_fetch(_item_id: int) -> None:
    """A fetch that finds nothing (digest then reads the feed snippet)."""


def test_run_pipeline_triages_digests_and_skips(engine, tmp_path) -> None:
    """New items are triaged; those over the gate and reader items are digested; switched-off
    feeds are skipped and counted."""
    high = add_item(engine, "High item")
    low = add_item(engine, "Low item")
    mine = add_item(engine, "Reader item", source="raindrop")
    set_state(engine, mine, from_user=True)
    add_feed(engine, "https://off.example/feed", enabled=False)
    off = add_item(engine, "Off item", feed_url="https://off.example/feed")
    store_text(engine, high)
    llm = FakeLlm(score_for=lambda i: 80 if i == high else 20)
    counts = run_pipeline(engine, make_settings(tmp_path), None, llm=llm, fetch=_no_fetch)
    assert counts == {"triaged": 3, "digested": 2, "failed": 0, "unreachable": 0, "skipped": 1,
                      "stopped": False}
    stored = _assessments(engine)
    assert stored[high].stage == "digest" and stored[mine].stage == "digest"
    assert stored[low].stage == "triage" and stored[low].tier == "out"
    assert off not in stored


def test_run_pipeline_is_idempotent(engine, tmp_path) -> None:
    """A second run finds nothing to do and makes no model calls."""
    add_item(engine, "One")
    add_item(engine, "Two")
    settings = make_settings(tmp_path)
    run_pipeline(engine, settings, None, llm=FakeLlm(), fetch=_no_fetch)
    llm = FakeLlm()
    counts = run_pipeline(engine, settings, None, llm=llm, fetch=_no_fetch)
    assert counts == {"triaged": 0, "digested": 0, "failed": 0, "unreachable": 0, "skipped": 0,
                      "stopped": False} and not llm.calls


def test_run_pipeline_takes_newest_first_and_respects_limit_and_since(engine, tmp_path) -> None:
    """limit picks the newest items; since leaves older ones alone."""
    old = add_item(engine, "Old", age_hours=48)
    middle = add_item(engine, "Middle", age_hours=10)
    new = add_item(engine, "New", age_hours=1)
    settings = make_settings(tmp_path)
    low = FakeLlm(score_for=lambda _i: 10)
    assert run_pipeline(engine, settings, None, limit=1, llm=low)["triaged"] == 1
    assert set(_assessments(engine)) == {new}
    since = utc(BASE_TIME - timedelta(hours=24))
    assert run_pipeline(engine, settings, None, since=since, llm=low)["triaged"] == 1
    assert set(_assessments(engine)) == {new, middle}
    assert old not in _assessments(engine)


def test_run_pipeline_default_window_ignores_the_old_backlog(engine, tmp_path) -> None:
    """Without since, only items from the last 7 days, and reader items from the last 30 days,
    are judged; an explicit since overrides the window."""
    recent = add_item(engine, "Recent", age_hours=24)
    old = add_item(engine, "Old backlog", age_hours=24 * 10)
    old_mine = add_item(engine, "Old reader item", source="raindrop", age_hours=24 * 10)
    ancient_mine = add_item(engine, "Ancient reader item", source="raindrop", age_hours=24 * 40)
    set_state(engine, old_mine, from_user=True)
    set_state(engine, ancient_mine, from_user=True)
    settings = make_settings(tmp_path)
    low = FakeLlm(score_for=lambda _i: 10)
    counts = run_pipeline(engine, settings, None, llm=low, fetch=_no_fetch)
    assert counts["triaged"] == 2 and set(_assessments(engine)) == {recent, old_mine}
    run_pipeline(engine, settings, None, since=utc(BASE_TIME - timedelta(days=60)), llm=low,
                 fetch=_no_fetch)
    assert {old, ancient_mine} <= set(_assessments(engine))


def test_run_pipeline_window_is_measured_from_now(engine, tmp_path) -> None:
    """`now` moves the default window; items newer than now - 7 days are in."""
    item_id = add_item(engine, "Item", age_hours=24 * 20)
    settings = make_settings(tmp_path)
    low = FakeLlm(score_for=lambda _i: 10)
    assert run_pipeline(engine, settings, None, llm=low)["triaged"] == 0
    then = utc(BASE_TIME - timedelta(days=18))
    assert run_pipeline(engine, settings, None, llm=low, now=then)["triaged"] == 1
    assert item_id in _assessments(engine)


def test_run_pipeline_leaves_items_pending_when_the_model_is_down(engine, tmp_path) -> None:
    """An outage stores nothing and counts failures; the next run judges the items."""
    add_item(engine, "One")
    add_item(engine, "Two")
    settings = make_settings(tmp_path)

    def hook(*_args):
        """Every call fails."""
        raise RuntimeError("down")

    counts = run_pipeline(engine, settings, None, llm=FakeLlm(hook=hook))
    assert counts["failed"] == 2 and counts["triaged"] == 0 and not _assessments(engine)
    counts = run_pipeline(engine, settings, None, llm=FakeLlm(score_for=lambda _i: 10))
    assert counts["triaged"] == 2


def test_run_pipeline_retries_digests_left_at_triage(engine, tmp_path) -> None:
    """An item over the gate whose digest failed earlier is digested on the next run."""
    item_id = add_item(engine, "Worth reading")
    settings = make_settings(tmp_path)

    def digest_down(_number: int, name: str, _messages: list[dict]):
        """Triage works; digest is unreachable."""
        if name == "digest":
            raise RuntimeError("timeout")
        return None

    first = run_pipeline(engine, settings, None, llm=FakeLlm(hook=digest_down), fetch=_no_fetch)
    assert first == {"triaged": 1, "digested": 0, "failed": 1, "unreachable": 1, "skipped": 0,
                     "stopped": False}
    second = run_pipeline(engine, settings, None, llm=FakeLlm(), fetch=_no_fetch)
    assert second["digested"] == 1 and _assessments(engine)[item_id].stage == "digest"


def test_triage_items_runs_batches_and_stores_every_item(engine, tmp_path) -> None:
    """45 items go out as three batches (in parallel) and every judgement is stored."""
    ids = [add_item(engine, f"Item {n}") for n in range(45)]
    llm = FakeLlm(score_for=lambda _i: 30)
    judge = pipeline.make_judge(engine, make_settings(tmp_path), llm=llm)
    assert pipeline.triage_items(engine, judge, ids) == {"triaged": 45, "failed": 0,
                                                         "unreachable": 0}
    assert llm.count("triage") == 3 and set(_assessments(engine)) == set(ids)


def test_triage_items_counts_a_crashed_batch(engine, tmp_path, monkeypatch) -> None:
    """A batch that raises unexpectedly counts its items as failed and stores nothing."""
    ids = [add_item(engine, "A"), add_item(engine, "B")]

    def crash(_judge, _rows):
        """Simulate a bug inside triage."""
        raise KeyError("bug")

    monkeypatch.setattr(pipeline, "triage_rows", crash)
    judge = pipeline.make_judge(engine, make_settings(tmp_path), llm=FakeLlm())
    assert pipeline.triage_items(engine, judge, ids) == {"triaged": 0, "failed": 2,
                                                         "unreachable": 0}
    assert not _assessments(engine)


def test_digest_items_counts_unexpected_errors_as_failed(engine, tmp_path, monkeypatch) -> None:
    """A digest that raises something unexpected is counted and does not stop the others."""
    first, second = add_item(engine, "A"), add_item(engine, "B")

    def flaky(_engine, _settings, _judge, item_id, **_kwargs):
        """Fail for the first item only."""
        if item_id == first:
            raise KeyError("bug")
        return object()

    monkeypatch.setattr(pipeline, "digest_one", flaky)
    counts = pipeline.digest_items(engine, make_settings(tmp_path), None, [first, second])
    assert counts == {"digested": 1, "failed": 1, "unreachable": 0}
    assert pipeline.digest_items(engine, make_settings(tmp_path), None, []) == {
        "digested": 0, "failed": 0, "unreachable": 0}


def test_run_pipeline_rejects_a_bad_limit(engine, tmp_path) -> None:
    """A limit under one is a caller error."""
    with pytest.raises(ValueError):
        run_pipeline(engine, make_settings(tmp_path), None, limit=0, llm=FakeLlm())


def test_backfill_from_user_marks_raindrop_and_slack_items(engine) -> None:
    """Raindrop bookmarks and Slack inbox items become reader items; a rerun changes nothing."""
    bookmark = add_item(engine, "Bookmark", source="raindrop")
    slack = add_item(engine, "Slack link", source="inbox")
    add_inbox_entry(engine, slack)
    feed_item = add_item(engine, "Feed item")
    assert backfill_from_user(engine) == 2
    assert backfill_from_user(engine) == 0
    with Session(engine) as session:
        states = {s.item_id: s for s in session.exec(select(ItemState)).all()}
    assert (states[bookmark].from_user, states[bookmark].captured_via) == (True, "raindrop")
    assert (states[slack].from_user, states[slack].captured_via) == (True, "slack")
    assert feed_item not in states


def test_backfill_from_user_updates_existing_state_and_tier(engine) -> None:
    """An existing state is flipped (its other fields kept) and an old tier is lifted."""
    bookmark = add_item(engine, "Bookmark", source="raindrop")
    set_state(engine, bookmark, vote="more", captured_via="share")
    pipeline.store_assessment(engine, bookmark, {"stage": "triage", "score": 20, "tier": "out"})
    assert backfill_from_user(engine) == 1
    with Session(engine) as session:
        state = session.exec(select(ItemState).where(ItemState.item_id == bookmark)).one()
    assert state.from_user and state.vote == "more" and state.captured_via == "share"
    assert _assessments(engine)[bookmark].tier == "notable"
