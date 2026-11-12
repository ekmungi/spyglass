"""Tests for the plain-text form of an item's assistant conversations (radar/thread_qa.py)."""

import pytest
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar.models import AssistMessage, AssistThread
from spyglass_service.radar.thread_qa import CUT_NOTE, QA_MAX, has_item_qa, item_qa_text


@pytest.fixture
def db(tmp_path):
    """A fresh database, disposed afterwards."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine
    engine.dispose()


def add_thread(engine, item_id: int | None, turns: list[tuple[str, str]]) -> None:
    """One thread on `item_id` with the given (role, text) turns."""
    with Session(engine) as session:
        thread = AssistThread(item_id=item_id, title="t")
        session.add(thread)
        session.commit()
        for role, text in turns:
            session.add(AssistMessage(thread_id=thread.id, role=role, content=text))
        session.commit()


def test_the_cap_is_about_six_thousand_characters():
    assert QA_MAX == 6_000


def test_has_item_qa_needs_a_question_on_that_item(db):
    with Session(db) as session:
        assert has_item_qa(session, 1) is False
    add_thread(db, 2, [("user", "elsewhere?")])
    add_thread(db, 1, [("assistant", "an answer with no question")])
    with Session(db) as session:
        assert has_item_qa(session, 1) is False
    add_thread(db, 1, [("user", "Is it solid?"), ("assistant", "Mostly.")])
    with Session(db) as session:
        assert has_item_qa(session, 1) is True and has_item_qa(session, 3) is False


def test_newest_first_puts_the_latest_conversation_first_and_cuts_the_oldest(db):
    add_thread(db, 1, [("user", "old question"), ("assistant", "old " * 2000)])
    add_thread(db, 1, [("user", "new question"), ("assistant", "new answer")])
    plain = item_qa_text(db, 1, 1000)
    # Oldest first, as before: the long old conversation pushes the new one out of the cap.
    assert "old question" in plain and "new question" not in plain
    text = item_qa_text(db, 1, 1000, newest_first=True)
    assert text.startswith("Q: new question\n\nA: new answer")
    assert text.index("new question") < text.index("old question") and text.endswith(CUT_NOTE)


def test_newest_first_keeps_each_conversation_in_reading_order(db):
    add_thread(db, 1, [("user", "first?"), ("assistant", "one"), ("user", "second?"),
                       ("assistant", "two")])
    text = item_qa_text(db, 1, 1000, newest_first=True)
    assert text.index("first?") < text.index("one") < text.index("second?") < text.index("two")
