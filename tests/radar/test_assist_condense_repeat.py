# ruff: noqa: F811
"""Tests that a long conversation is condensed once, not again on every following turn."""

from sqlmodel import Session

from spyglass_service.radar.assist import condense, threads
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.threads import AssistMessage

from .test_assist_condense import add_row
from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    make_settings,
    patch_fake_engine,
)

SUMMARY = [StreamEvent.delta("Summary text."), StreamEvent.done()]
ANSWER = [StreamEvent.session("S2"), StreamEvent.delta("An answer."), StreamEvent.done()]


class ScriptedEngine(FakeEngine):
    """A fake engine whose Nth call plays the Nth script (the last script repeats)."""

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        """`scripts` is one event list per call."""
        super().__init__([], id="claude_code")
        self.scripts = scripts

    def stream(self, *, system, messages, model, session=None):
        """Record the call and play this call's script."""
        self.events = self.scripts[min(len(self.calls), len(self.scripts) - 1)]
        return super().stream(system=system, messages=messages, model=model, session=session)


def long_thread(db, messages: int = 70) -> int:
    """A claude_code thread resumed from session S1 with `messages` stored messages."""
    tid = threads.create_or_get_thread(db, item_id=add_item(db))["id"]
    with Session(db) as session:
        thread = session.get(threads.AssistThread, tid)
        thread.engine, thread.model, thread.external_session = "claude_code", "sonnet", "S1"
        for n in range(messages // 2):
            session.add(AssistMessage(thread_id=tid, role="user", content=f"Question {n}"))
            session.add(AssistMessage(thread_id=tid, role="assistant", content=f"Answer {n}"))
        session.add(thread)
        session.commit()
    return tid


def turn(db, tmp_path, tid: int, stop_after_delta: bool = False) -> list[dict]:
    """Run one turn and return its events; optionally close the generator at the first delta."""
    gen = threads.run_turn(db, make_settings(tmp_path), tid, content="And now?")
    events: list[dict] = []
    for event in gen:
        events.append(event)
        if stop_after_delta and event["type"] == "delta":
            gen.close()
            break
    return events


def session_of(db, tid: int) -> str | None:
    """The session id the thread currently points at."""
    with Session(db) as session:
        return session.get(threads.AssistThread, tid).external_session


def test_a_thread_past_the_fallback_limit_is_condensed_once_and_not_again(db, tmp_path, monkeypatch):
    engine = ScriptedEngine([SUMMARY, ANSWER, ANSWER, ANSWER])
    patch_fake_engine(monkeypatch, engine)
    tid = long_thread(db)
    turn(db, tmp_path, tid)
    assert len(engine.calls) == 2 and engine.calls[1]["session"] is None  # summary, then fresh answer
    assert session_of(db, tid) == "S2"
    turn(db, tmp_path, tid)
    turn(db, tmp_path, tid)
    assert len(engine.calls) == 4  # one answer call per later turn, no further summary
    assert [c["session"] for c in engine.calls[2:]] == ["S2", "S2"]


def test_a_condensed_turn_that_fails_does_not_condense_again(db, tmp_path, monkeypatch):
    engine = ScriptedEngine([SUMMARY, [StreamEvent.session("S2"), StreamEvent.error("boom")], ANSWER])
    patch_fake_engine(monkeypatch, engine)
    tid = long_thread(db, messages=4)
    add_row(db, tid, fresh=True, context=12_000, age=30)
    add_row(db, tid, fresh=False, context=12_000 + condense.LIMIT_TOKENS, age=10)
    assert turn(db, tmp_path, tid)[-1]["type"] == "error"
    assert session_of(db, tid) == "S2"  # the thread no longer points at the over-limit session
    turn(db, tmp_path, tid)
    assert len(engine.calls) == 3 and engine.calls[2]["session"] == "S2"  # no second summary


def test_a_failure_without_a_session_id_clears_the_old_over_limit_session(db, tmp_path, monkeypatch):
    engine = ScriptedEngine([SUMMARY, [StreamEvent.error("boom")], ANSWER])
    patch_fake_engine(monkeypatch, engine)
    tid = long_thread(db)
    turn(db, tmp_path, tid)
    assert session_of(db, tid) is None
    turn(db, tmp_path, tid)
    assert len(engine.calls) == 3  # summary, failed answer, then one more answer: no new summary


def test_a_condensed_turn_that_is_stopped_does_not_condense_again(db, tmp_path, monkeypatch):
    engine = ScriptedEngine([SUMMARY, ANSWER, ANSWER])
    patch_fake_engine(monkeypatch, engine)
    tid = long_thread(db)
    turn(db, tmp_path, tid, stop_after_delta=True)
    assert session_of(db, tid) == "S2"
    turn(db, tmp_path, tid)
    assert len(engine.calls) == 3 and engine.calls[2]["session"] == "S2"


def test_the_measured_path_still_condenses_on_growth_and_ignores_rows_before_the_summary(db):
    tid = 7
    add_row(db, tid, fresh=True, context=12_000, age=30)
    add_row(db, tid, fresh=False, context=12_000 + condense.LIMIT_TOKENS, age=10)
    assert condense.needs_condensing(db, tid, 6)
    condense.save_summary(db, tid, 6, "s", usage_floor=condense.latest_usage_id(db, tid))
    assert not condense.needs_condensing(db, tid, 8)  # the old rows belong to the replaced session
    add_row(db, tid, fresh=True, context=3_000, age=5)
    add_row(db, tid, fresh=False, context=3_000 + condense.LIMIT_TOKENS, age=1)
    assert condense.needs_condensing(db, tid, 10)


def test_the_fallback_count_starts_after_what_the_summary_covers(db):
    assert condense.needs_condensing(db, 9, condense.FALLBACK_MESSAGES)
    condense.save_summary(db, 9, condense.FALLBACK_MESSAGES, "s")
    assert not condense.needs_condensing(db, 9, condense.FALLBACK_MESSAGES + 4)
    assert condense.needs_condensing(db, 9, 2 * condense.FALLBACK_MESSAGES)
