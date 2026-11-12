"""Regression tests: bad model replies are retried a bounded number of times, outages are not
counted as attempts, error text never reaches the reader, and a run can be stopped."""

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.assess import store_assessment
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.pipeline import run_pipeline
from spyglass_service.radar.serialize import radar_items

from .test_assess_support import FakeLlm, add_item, make_engine, make_settings


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _row(engine, item_id: int) -> Assessment:
    """The stored assessment of one item."""
    with Session(engine) as session:
        return session.exec(select(Assessment).where(Assessment.item_id == item_id)).one()


def _item(engine, item_id: int) -> dict:
    """The RadarItem shape of one item."""
    with Session(engine) as session:
        return radar_items(session, [item_id])[0]


def test_unusable_digest_stops_after_two_attempts_and_keeps_the_triage_score(engine, tmp_path):
    """A digest reply that is never usable is tried on two runs only, then left at triage."""
    item_id = add_item(engine, "High item")
    fetches: list[int] = []
    llm = FakeLlm(score_for=lambda _i: 90, digest={"nonsense": 1})
    settings = make_settings(tmp_path)
    for _ in range(5):
        run_pipeline(engine, settings, None, llm=llm, fetch=fetches.append)
    assert llm.count("digest") == 4  # two runs, each with its one in-call retry
    assert len(fetches) == 2
    row = _row(engine, item_id)
    assert (row.stage, row.score, row.tier) == ("triage", 90, "top")
    assert row.digest_attempts == 2 and "unusable" in (row.error or "")
    assert _item(engine, item_id)["why"] is None


def test_a_digest_outage_does_not_use_up_an_attempt(engine, tmp_path):
    """An unreachable model leaves the attempt counter alone and is reported as unreachable."""
    item_id = add_item(engine, "Worth reading")
    settings = make_settings(tmp_path)

    def digest_down(_n: int, name: str, _messages: list[dict]):
        """Triage works; the digest model cannot be reached."""
        if name == "digest":
            raise RuntimeError("connection refused")
        return None

    for _ in range(3):
        counts = run_pipeline(engine, settings, None, llm=FakeLlm(hook=digest_down),
                              fetch=lambda _i: None)
        assert counts["unreachable"] == 1
    assert _row(engine, item_id).digest_attempts == 0
    run_pipeline(engine, settings, None, llm=FakeLlm(), fetch=lambda _i: None)
    assert _row(engine, item_id).stage == "digest"


def test_a_malformed_triage_is_stored_apart_and_retried_on_the_next_run(engine, tmp_path):
    """One bad triage reply is recorded as triage_failed with the error kept out of `why`, and
    the next run with a working model judges the item properly."""
    item_id = add_item(engine, "Important item")
    settings = make_settings(tmp_path)
    run_pipeline(engine, settings, None, llm=FakeLlm(hook=lambda *_a: {"oops": True}),
                 fetch=lambda _i: None)
    row = _row(engine, item_id)
    assert (row.stage, row.tier, row.why, row.triage_attempts) == ("triage_failed", "unjudged",
                                                                   None, 1)
    assert "triage failed" in (row.error or "")
    shown = _item(engine, item_id)
    assert shown["tier"] == "unjudged" and shown["why"] is None and shown["score"] is None
    good = FakeLlm(score_for=lambda _i: 95)
    run_pipeline(engine, settings, None, llm=good, fetch=lambda _i: None)
    assert good.count("triage") == 1
    row = _row(engine, item_id)
    # Triaged at 95 (over the gate), then digested; the digest reply scores 88.
    assert row.stage == "digest" and row.score == 88 and row.error is None


def test_triage_is_given_up_after_three_failed_runs_and_the_item_stays_unjudged(engine, tmp_path):
    """After three failed runs the item is no longer sent to the model and is never 'out'."""
    item_id = add_item(engine, "Odd item")
    settings = make_settings(tmp_path)
    bad = FakeLlm(hook=lambda *_a: {"oops": True})
    for _ in range(4):
        run_pipeline(engine, settings, None, llm=bad, fetch=lambda _i: None)
    assert bad.count("triage") == 6  # three runs, each a batch call plus one solo retry
    row = _row(engine, item_id)
    assert row.triage_attempts == 3 and row.tier == "unjudged" and row.stage == "triage_failed"


def test_old_failed_triage_rows_are_converted_and_judged_again(engine, tmp_path):
    """Rows stored by the earlier code (score 0, reason in why) become retryable failures."""
    item_id = add_item(engine, "Old failure")
    store_assessment(engine, item_id, {"stage": "triage", "score": 0, "tier": "out",
                                       "why": "triage failed: reply missing or malformed twice"})
    llm = FakeLlm(score_for=lambda _i: 30)
    run_pipeline(engine, make_settings(tmp_path), None, llm=llm, fetch=lambda _i: None)
    row = _row(engine, item_id)
    assert llm.count("triage") == 1 and row.score == 30 and row.why is None


def test_run_pipeline_reports_an_outage_as_unreachable(engine, tmp_path):
    """A model that cannot be reached at all is counted separately from bad replies."""
    add_item(engine, "One")
    add_item(engine, "Two")

    def down(*_args):
        """Every call fails to connect."""
        raise RuntimeError("down")

    counts = run_pipeline(engine, make_settings(tmp_path), None, llm=FakeLlm(hook=down))
    assert counts["unreachable"] == 2 and counts["triaged"] == 0


def test_run_pipeline_stops_between_batches_when_asked(engine, tmp_path):
    """A stop request before the run starts sends nothing to the model."""
    for n in range(3):
        add_item(engine, f"Item {n}")
    llm = FakeLlm()
    counts = run_pipeline(engine, make_settings(tmp_path), None, llm=llm, fetch=lambda _i: None,
                          should_stop=lambda: True)
    assert not llm.calls and counts["triaged"] == 0 and counts["stopped"] is True
