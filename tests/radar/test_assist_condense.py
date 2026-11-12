# ruff: noqa: F811
"""Tests for condensing a long conversation into a short written summary."""

from datetime import timedelta

from sqlmodel import Session, select

from spyglass_service.radar import usage
from spyglass_service.radar.assist import condense, threads
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.threads import AssistMessage
from spyglass_service.radar.models import RadarDoc, utcnow
from spyglass_service.radar.usage_parse import Tokens

from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    make_settings,
    patch_fake_engine,
)


def turns(count: int, size: int = 100) -> list[dict]:
    """`count` question-and-answer pairs plus a new question, as the engine would be given them."""
    messages: list[dict] = []
    for n in range(count):
        messages += [{"role": "user", "content": f"Question {n} " + "q" * size},
                     {"role": "assistant", "content": f"Answer {n} " + "a" * size}]
    return [*messages, {"role": "user", "content": "The new question"}]


def add_row(db, thread_id: int, *, fresh: bool, context: int | None, age: float = 0.0) -> None:
    """A usage row for the thread whose prompt was `context` tokens."""
    with Session(db) as session:
        session.add(usage.UsageCall(
            at=utcnow() - timedelta(minutes=age), purpose="chat", provider="claude_code",
            model="haiku", thread_id=thread_id, fresh=fresh, message_id=1,
            input_tokens=None if context is None else 2,
            cache_read_tokens=None if context is None else context - 2, output_tokens=1))
        session.commit()


def test_growth_is_the_context_now_minus_the_context_of_the_sessions_first_turn(db):
    add_row(db, 1, fresh=True, context=12_000, age=30)
    add_row(db, 1, fresh=False, context=13_000, age=20)
    add_row(db, 1, fresh=False, context=33_500, age=10)
    assert condense.history_growth(db, 1) == 21_500


def test_growth_starts_again_at_the_latest_new_session(db):
    add_row(db, 1, fresh=True, context=12_000, age=40)
    add_row(db, 1, fresh=False, context=40_000, age=30)
    add_row(db, 1, fresh=True, context=13_000, age=20)
    add_row(db, 1, fresh=False, context=14_000, age=10)
    assert condense.history_growth(db, 1) == 1_000


def test_growth_is_unknown_without_figures(db):
    add_row(db, 1, fresh=True, context=None)
    assert condense.history_growth(db, 1) is None and condense.history_growth(db, 99) is None


def test_a_conversation_is_condensed_when_the_measured_growth_passes_the_limit(db):
    add_row(db, 1, fresh=True, context=12_000, age=30)
    add_row(db, 1, fresh=False, context=12_000 + condense.LIMIT_TOKENS, age=10)
    assert condense.needs_condensing(db, 1, 6)
    add_row(db, 2, fresh=True, context=12_000, age=30)
    add_row(db, 2, fresh=False, context=12_000 + condense.LIMIT_TOKENS - 1, age=10)
    assert not condense.needs_condensing(db, 2, 6)


def test_without_figures_a_turn_count_decides(db):
    assert not condense.needs_condensing(db, 5, condense.FALLBACK_MESSAGES - 1)
    assert condense.needs_condensing(db, 5, condense.FALLBACK_MESSAGES)


def test_the_cheaper_model_of_the_route_is_used_for_the_summary():
    assert condense.cheap_model("claude_code", "sonnet") == "haiku"
    assert condense.cheap_model("anthropic", "claude-sonnet-5-5") == "claude-haiku-5-5"
    assert condense.cheap_model("ollama", "llama3") == "llama3"


def test_summary_messages_open_with_a_reader_turn_and_say_they_are_condensed():
    pair = condense.summary_messages("They asked about X.")
    assert [m["role"] for m in pair] == ["user", "assistant"] and "They asked about X." in pair[0]["content"]


def runner(engine):
    """A stream runner that calls the fake engine without a session."""
    return lambda system, messages, model: engine.stream(system=system, messages=messages,
                                                         model=model, session=None)


def test_summarize_collects_the_streamed_text_and_the_figures():
    engine = FakeEngine([StreamEvent.delta("The reader "), StreamEvent.delta("asked X."),
                         StreamEvent.usage(Tokens(input=5, output=7)), StreamEvent.done()])
    text, tokens = condense.summarize(runner(engine), "m1", turns(2)[:-1], None)
    assert text == "The reader asked X." and tokens == Tokens(input=5, output=7)
    call = engine.calls[0]
    assert call["session"] is None and "Question 0" in call["messages"][0]["content"]
    assert condense.SUMMARY_WORDS and str(condense.SUMMARY_WORDS) in call["system"]


def test_summarize_returns_nothing_when_the_engine_fails():
    engine = FakeEngine([StreamEvent.delta("partial"), StreamEvent.error("down")])
    assert condense.summarize(runner(engine), "m1", turns(1)[:-1], None) == (None, None)


def test_summarize_includes_the_earlier_summary():
    engine = FakeEngine([StreamEvent.delta("New summary."), StreamEvent.done()])
    condense.summarize(runner(engine), "m1", turns(1)[:-1], "Old summary.")
    assert "Old summary." in engine.calls[0]["messages"][0]["content"]


def test_fit_history_leaves_a_short_conversation_alone(db):
    sent, summary_used = condense.fit_history(db, 1, turns(2), lambda earlier, prior: ("S", None))
    assert sent == turns(2) and summary_used is False


def test_fit_history_replaces_dropped_turns_with_a_summary(db):
    messages = turns(40, size=1_000)  # far over the history budget
    calls: list[int] = []

    def summarizer(earlier, prior):
        calls.append(len(earlier))
        return "SUMMARY OF EARLIER", None

    sent, used = condense.fit_history(db, 1, messages, summarizer)
    assert used and "SUMMARY OF EARLIER" in sent[0]["content"] and sent[0]["role"] == "user"
    assert sent[-1] == messages[-1] and len(calls) == 1 and sent[1]["role"] == "assistant"
    assert sent[2]["role"] == "user"
    again, _ = condense.fit_history(db, 1, messages, summarizer)
    assert again == sent and len(calls) == 1  # the stored summary is reused


def test_fit_history_summarizes_again_only_after_several_more_messages_dropped(db):
    summarizer_calls: list[int] = []

    def summarizer(earlier, prior):
        summarizer_calls.append(len(earlier))
        return f"SUMMARY {len(summarizer_calls)}", None

    condense.fit_history(db, 1, turns(40, size=1_000), summarizer)
    condense.fit_history(db, 1, turns(41, size=1_000), summarizer)   # two more messages: reuse
    assert len(summarizer_calls) == 1
    condense.fit_history(db, 1, turns(46, size=1_000), summarizer)   # ten more: summarize again
    assert len(summarizer_calls) == 2


def test_fit_history_falls_back_to_dropping_when_the_summary_cannot_be_made(db):
    messages = turns(40, size=1_000)
    sent, used = condense.fit_history(db, 1, messages, lambda earlier, prior: (None, None))
    assert used is False and sent == condense_trim(messages)


def condense_trim(messages):
    """What the plain history budget keeps."""
    from spyglass_service.radar.assist import context

    return context.trim_history(messages)


def test_a_long_resumed_conversation_starts_a_fresh_session_from_a_summary(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    engine = FakeEngine([StreamEvent.session("S2"), StreamEvent.delta("Summary text."),
                         StreamEvent.usage(Tokens(input=3, output=9)), StreamEvent.done()],
                        id="claude_code")
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    with Session(db) as session:
        thread = session.get(threads.AssistThread, tid)
        thread.engine, thread.model, thread.external_session = "claude_code", "sonnet", "S1"
        for n in range(3):
            session.add(AssistMessage(thread_id=tid, role="user", content=f"Earlier question {n}"))
            session.add(AssistMessage(thread_id=tid, role="assistant", content=f"Earlier answer {n}"))
        session.add(thread)
        session.commit()
    add_row(db, tid, fresh=True, context=12_000, age=30)
    add_row(db, tid, fresh=False, context=12_000 + condense.LIMIT_TOKENS, age=10)
    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="And now?"))
    summary_call, answer_call = engine.calls
    assert summary_call["model"] == "haiku" and summary_call["session"] is None
    assert answer_call["session"] is None  # a fresh session, not a resume of S1
    assert "Summary text." in answer_call["messages"][0]["content"]
    assert answer_call["messages"][-1]["content"].endswith("And now?")
    assert events[-1]["type"] == "done" and events[-1]["usage"]["condensed"] is True
    with Session(db) as session:
        rows = list(session.exec(select(usage.UsageCall).where(usage.UsageCall.thread_id == tid)
                                 .order_by(usage.UsageCall.id)).all())
        saved = session.get(RadarDoc, f"assist_summary:{tid}")
    assert rows[-1].condensed is True and rows[-1].fresh is True and rows[-2].model == "haiku"
    assert saved is not None and "Summary text." in saved.body
    assert len(threads.thread_detail(db, tid)["messages"]) == 8  # the whole conversation stays stored


def test_a_failed_summary_leaves_the_session_to_be_resumed(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    engine = FakeEngine([StreamEvent.error("down")], id="claude_code")
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    with Session(db) as session:
        thread = session.get(threads.AssistThread, tid)
        thread.engine, thread.model, thread.external_session = "claude_code", "sonnet", "S1"
        session.add(thread)
        session.commit()
    add_row(db, tid, fresh=True, context=12_000, age=30)
    add_row(db, tid, fresh=False, context=12_000 + condense.LIMIT_TOKENS, age=10)
    events = list(threads.run_turn(db, make_settings(tmp_path), tid, content="And now?"))
    assert engine.calls[-1]["session"] == "S1"
    assert events[-1]["type"] == "error"
