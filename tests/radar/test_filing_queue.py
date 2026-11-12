"""Tests for the filing queue (radar/filing_queue.py): the table, its functions and its hooks.

Everything runs on a temporary database; the vault is only a temporary folder.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_queue
from spyglass_service.radar.filed import record_filed
from spyglass_service.radar.models import Assessment, dumps
from spyglass_service.radar.serialize import radar_items


@pytest.fixture
def engine(tmp_path):
    """A fresh database with the radar tables."""
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def add_item(engine, n: int = 1) -> int:
    """One judged item; returns its id."""
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"e{n}", title=f"Title {n}",
                    url=f"https://site.example/{n}", origin="Site Example",
                    published_at=datetime(2026, 11, 9, tzinfo=UTC))
        session.add(item)
        session.commit()
        session.add(Assessment(item_id=item.id, tier="top", section="health", kind="news",
                               score=80, headline=f"Headline {n}", key_points=dumps([]),
                               entities=dumps([])))
        session.commit()
        return item.id


def test_enqueue_adds_a_row_with_defaults(engine):
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id)
    [entry] = filing_queue.waiting(engine)
    assert (entry.item_id, entry.kind, entry.project, entry.note) == (item_id, "resource", None, "")
    assert filing_queue.count(engine) == 1


def test_enqueue_twice_updates_the_row_instead_of_adding_one(engine):
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id)
    filing_queue.enqueue(engine, item_id, kind="feature idea", project="Imaging", note="later")
    [entry] = filing_queue.waiting(engine)
    assert (entry.kind, entry.project, entry.note) == ("feature idea", "Imaging", "later")


def test_note_is_one_clean_line_of_at_most_500_characters(engine):
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id, note="line one\nline two\t" + "x" * 600)
    [entry] = filing_queue.waiting(engine)
    assert "\n" not in entry.note and "\t" not in entry.note
    assert len(entry.note) <= 500


def test_unknown_kind_is_refused(engine):
    item_id = add_item(engine)
    with pytest.raises(ValueError):
        filing_queue.enqueue(engine, item_id, kind="poem")
    assert filing_queue.count(engine) == 0


def test_waiting_lists_the_oldest_first(engine):
    first, second = add_item(engine, 1), add_item(engine, 2)
    filing_queue.enqueue(engine, second)
    filing_queue.enqueue(engine, first)
    assert [e.item_id for e in filing_queue.waiting(engine)] == [second, first]
    # Changing the older row does not send it to the back of the queue.
    filing_queue.enqueue(engine, second, note="changed")
    assert [e.item_id for e in filing_queue.waiting(engine)] == [second, first]


def test_dequeue_reports_whether_a_row_was_removed(engine):
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id)
    assert filing_queue.dequeue(engine, item_id) is True
    assert filing_queue.dequeue(engine, item_id) is False
    assert filing_queue.count(engine) == 0


def test_the_table_is_added_to_an_existing_database(tmp_path):
    """A database made before the queue existed gets the table at the next start."""
    eng = create_db_engine(tmp_path / "old.db")
    init_db(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE filing_queue"))
    init_db(eng)
    item_id = add_item(eng)
    filing_queue.enqueue(eng, item_id)
    assert filing_queue.count(eng) == 1
    eng.dispose()


def test_items_carry_the_waiting_marker(engine):
    queued, other = add_item(engine, 1), add_item(engine, 2)
    filing_queue.enqueue(engine, queued)
    with Session(engine) as session:
        items = {i["id"]: i for i in radar_items(session, [queued, other])}
    assert items[queued]["filing"] == "waiting"
    assert items[other]["filing"] is None


def test_recording_a_filing_removes_the_queue_row(engine, tmp_path):
    vault = tmp_path / "vault"
    (vault / "Notes").mkdir(parents=True)
    (vault / "Notes" / "a.md").write_text("x", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id)
    result = record_filed(engine, settings, item_id, "Notes/a.md")
    assert result["recorded"] is True
    assert filing_queue.count(engine) == 0


def test_a_failed_filing_leaves_the_queue_row(engine, tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path)
    item_id = add_item(engine)
    filing_queue.enqueue(engine, item_id)
    assert record_filed(engine, settings, item_id, "missing.md")["error"] == "no_file"
    assert filing_queue.count(engine) == 1


def test_check_project_accepts_listed_names_and_refuses_others(engine, tmp_path):
    vault = tmp_path / "vault"
    (vault / "01 PROJECTS" / "Imaging Radar").mkdir(parents=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    with Session(engine) as session:
        assert filing_queue.check_project(session, settings, "imaging radar") == "Imaging Radar"
        assert filing_queue.check_project(session, settings, None) is None
        assert filing_queue.check_project(session, settings, "  ") is None
        with pytest.raises(ValueError, match="not one of your projects"):
            filing_queue.check_project(session, settings, "Secret")
