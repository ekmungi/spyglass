"""Tests for the background run's one question per filed item (radar/filing_questions.py)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_questions as fq
from spyglass_service.radar import filing_queue
from spyglass_service.radar.filing_tables import FilingQuestion, plain_line
from spyglass_service.radar.models import ItemExtra, dumps, loads

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    """A database, settings with a vault holding three projects, and two items."""
    for name in ("Alpha Imaging", "Beta", "Gamma Lab"):
        (tmp_path / "vault" / "01 PROJECTS" / name).mkdir(parents=True)
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path / "vault")
    with Session(engine) as session:
        items = [Item(source="rss", external_id=f"e{n}", title=f"Title {n}",
                      url=f"https://site.example/{n}") for n in (1, 2)]
        session.add_all(items)
        session.commit()
        ids = [i.id for i in items]
    yield engine, settings, ids
    engine.dispose()


def file_item(engine, item_id: int, project: str | None = None) -> None:
    """Record the item as filed at a note path, as radar_mark_filed would."""
    with Session(engine) as session:
        session.add(ItemExtra(item_id=item_id, data=dumps(
            {"filed": {"path": f"03 RESOURCES/Note {item_id}.md", "project": project,
                       "at": NOW.isoformat()}})))
        session.commit()


def test_the_tables_exist_after_init_db(env):
    engine, _settings, _ids = env
    names = inspect(engine).get_table_names()
    assert "filing_question" in names and "filing_proposal" in names


def test_init_db_adds_the_tables_to_an_existing_database(tmp_path):
    engine = create_db_engine(tmp_path / "old.db")
    Item.__table__.create(engine)  # an older database: only some tables
    init_db(engine)
    assert "filing_question" in inspect(engine).get_table_names()
    engine.dispose()


def test_asking_stores_up_to_three_listed_projects_plus_no_project(env):
    engine, settings, (one, _two) = env
    file_item(engine, one)
    result = fq.ask(engine, settings, one, ["alpha imaging", "Beta", "No project"], now=NOW)
    assert result == {"asked": True, "item_id": one, "question": fq.QUESTION,
                      "options": ["Alpha Imaging", "Beta", fq.NO_PROJECT]}
    [row] = fq.open_questions(engine, now=NOW)
    assert row["options"] == ["Alpha Imaging", "Beta", fq.NO_PROJECT]
    assert row["question"] == "Link this to a project?"


@pytest.mark.parametrize("options, error", [
    ([], "invalid_options"),
    (["Delta"], "invalid_options"),
    (["Alpha Imaging", "Beta", "Gamma Lab", "Alpha Imaging"], None),
    (["Alpha Imaging", "Beta", "Gamma Lab", "No project", "Beta"], None),
    ("Beta", "invalid_options"),
    (["Alpha Imaging", "Beta", "Gamma Lab", "Delta"], "invalid_options"),
])
def test_options_are_checked_against_the_project_list(env, options, error):
    engine, settings, (one, _two) = env
    file_item(engine, one)
    result = fq.ask(engine, settings, one, options, now=NOW)
    if error:
        assert result["error"] == error
    else:
        assert result["options"] == ["Alpha Imaging", "Beta", "Gamma Lab", fq.NO_PROJECT]


def test_more_than_three_distinct_projects_is_refused(env, tmp_path):
    engine, settings, (one, _two) = env
    (tmp_path / "vault" / "01 PROJECTS" / "Delta").mkdir()
    file_item(engine, one)
    result = fq.ask(engine, settings, one, ["Alpha Imaging", "Beta", "Gamma Lab", "Delta"], now=NOW)
    assert result["error"] == "invalid_options"


def test_an_item_neither_filed_nor_queued_cannot_be_asked_about(env):
    engine, settings, (one, _two) = env
    assert fq.ask(engine, settings, one, ["Beta"], now=NOW)["error"] == "not_filed"
    assert fq.ask(engine, settings, 99999, ["Beta"], now=NOW)["error"] == "not_found"


def test_a_project_the_reader_chose_is_never_asked_about(env):
    engine, settings, (one, two) = env
    file_item(engine, one, project="Beta")
    filing_queue.enqueue(engine, two, project="Gamma Lab")
    assert fq.ask(engine, settings, one, ["Beta"], now=NOW)["error"] == "project_chosen"
    assert fq.ask(engine, settings, two, ["Beta"], now=NOW)["error"] == "project_chosen"


def test_asking_again_replaces_the_open_question(env):
    engine, settings, (one, _two) = env
    file_item(engine, one)
    fq.ask(engine, settings, one, ["Beta"], now=NOW)
    fq.ask(engine, settings, one, ["Gamma Lab"], now=NOW)
    [row] = fq.open_questions(engine, now=NOW)
    assert row["options"] == ["Gamma Lab", fq.NO_PROJECT]


def test_one_submit_answers_every_line_and_no_project_needs_no_run(env):
    engine, settings, (one, two) = env
    file_item(engine, one)
    file_item(engine, two)
    fq.ask(engine, settings, one, ["Beta"], now=NOW)
    fq.ask(engine, settings, two, ["Gamma Lab"], now=NOW)
    first, second = fq.open_questions(engine, now=NOW)
    result = fq.submit_answers(engine, [(first["id"], "Beta"), (second["id"], fq.NO_PROJECT)],
                               now=NOW)
    assert result == {"answered": 2}
    assert fq.open_questions(engine, now=NOW) == []
    assert fq.answered_unapplied(engine) == [
        {"question_id": first["id"], "item_id": one, "project": "Beta",
         "note_path": f"03 RESOURCES/Note {one}.md"}]


def test_a_bad_answer_changes_nothing(env):
    engine, settings, (one, two) = env
    file_item(engine, one)
    file_item(engine, two)
    fq.ask(engine, settings, one, ["Beta"], now=NOW)
    fq.ask(engine, settings, two, ["Beta"], now=NOW)
    first, second = fq.open_questions(engine, now=NOW)
    with pytest.raises(ValueError, match="not one of the choices"):
        fq.submit_answers(engine, [(first["id"], "Beta"), (second["id"], "Gamma Lab")], now=NOW)
    with pytest.raises(ValueError, match="no longer open"):
        fq.submit_answers(engine, [(first["id"], "Beta"), (424242, "Beta")], now=NOW)
    assert len(fq.open_questions(engine, now=NOW)) == 2


def test_an_unanswered_question_expires_after_fourteen_days_and_changes_nothing(env):
    engine, settings, (one, _two) = env
    file_item(engine, one)
    fq.ask(engine, settings, one, ["Beta"], now=NOW)
    later = NOW + timedelta(days=fq.EXPIRE_DAYS, minutes=1)
    assert fq.open_questions(engine, now=later) == []
    question_id = fq.open_questions(engine, now=NOW)[0]["id"]
    with pytest.raises(ValueError, match="no longer open"):
        fq.submit_answers(engine, [(question_id, "Beta")], now=later)
    assert fq.expire_questions(engine, now=later) == 1
    with Session(engine) as session:
        assert session.exec(select(FilingQuestion)).all() == []
        extra = session.exec(select(ItemExtra).where(ItemExtra.item_id == one)).one()
    assert loads(extra.data)["filed"]["project"] is None


def test_applying_an_answer_records_the_project_on_the_filed_item(env):
    engine, settings, (one, _two) = env
    file_item(engine, one)
    fq.ask(engine, settings, one, ["Beta"], now=NOW)
    question = fq.open_questions(engine, now=NOW)[0]
    fq.submit_answers(engine, [(question["id"], "Beta")], now=NOW)
    assert fq.mark_applied(engine, one, now=NOW) == {"applied": True, "item_id": one,
                                                     "project": "Beta"}
    assert fq.answered_unapplied(engine) == []
    with Session(engine) as session:
        extra = session.exec(select(ItemExtra).where(ItemExtra.item_id == one)).one()
    assert loads(extra.data)["filed"]["project"] == "Beta"
    assert fq.mark_applied(engine, one, now=NOW)["error"] == "nothing_to_apply"


def test_plain_line_drops_markup_and_line_breaks():
    assert plain_line("**Bold** [link](https://x.example)\n<script>`x`</script>", 80) == \
        "Bold link scriptx/script"
    assert len(plain_line("word " * 100, 20)) <= 20
