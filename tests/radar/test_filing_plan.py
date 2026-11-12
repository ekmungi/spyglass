"""Tests for the "show me the plan first" proposals (radar/filing_plan.py)."""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import filing_plan as fp
from spyglass_service.radar import filing_queue
from spyglass_service.radar.filed import record_filed

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    """A database, a vault with two projects, and three queued items."""
    for name in ("Alpha Imaging", "Beta"):
        (tmp_path / "vault" / "01 PROJECTS" / name).mkdir(parents=True)
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=tmp_path / "vault")
    with Session(engine) as session:
        items = [Item(source="rss", external_id=f"e{n}", title=f"Title {n}",
                      url=f"https://site.example/{n}") for n in (1, 2, 3)]
        session.add_all(items)
        session.commit()
        ids = [i.id for i in items]
    filing_queue.enqueue(engine, ids[0])
    filing_queue.enqueue(engine, ids[1], project="Beta", note="for the sizing work")
    filing_queue.enqueue(engine, ids[2])
    yield engine, settings, ids
    engine.dispose()


def propose(engine, settings, item_id, **changes):
    """A valid proposal with optional changes."""
    fields = {"becomes": "resource note", "place": "03 RESOURCES/Papers/AI",
              "name": "20261112_Sample_Paper", "project": None, "unsure": False,
              "reason": "", **changes}
    return fp.propose(engine, settings, item_id, now=NOW, **fields)


def test_a_proposal_is_stored_cleaned_and_listed(env):
    engine, settings, (one, _two, _three) = env
    result = propose(engine, settings, one, becomes="resource **note**\n", unsure=True,
                     reason="Two fields fit: <b>AI</b> and Medicine.")
    assert result["proposed"] is True
    [row] = fp.plan_rows(engine)
    assert row["item_id"] == one and row["becomes"] == "resource note"
    assert row["unsure"] is True and row["reason"] == "Two fields fit: bAI/b and Medicine."
    assert row["decision"] == "pending" and row["project"] is None


def test_proposing_again_replaces_the_row(env):
    engine, settings, (one, _two, _three) = env
    propose(engine, settings, one)
    propose(engine, settings, one, name="20261112_Better_Name")
    [row] = fp.plan_rows(engine)
    assert row["name"] == "20261112_Better_Name"


@pytest.mark.parametrize("changes, error", [
    ({"place": "../outside"}, "invalid_place"),
    ({"place": "C:/Temp/x"}, "invalid_place"),
    ({"place": ""}, "invalid_place"),
    ({"becomes": ""}, "invalid_proposal"),
    ({"name": "   "}, "invalid_proposal"),
    ({"project": "Nowhere"}, "unknown_project"),
])
def test_bad_proposals_are_refused(env, changes, error):
    engine, settings, (one, _two, _three) = env
    assert propose(engine, settings, one, **changes)["error"] == error
    assert fp.plan_rows(engine) == []


def test_the_project_the_reader_chose_is_followed_exactly(env):
    engine, settings, (_one, two, _three) = env
    assert propose(engine, settings, two, project="Alpha Imaging")["error"] == "project_chosen"
    assert propose(engine, settings, two)["proposed"] is True  # empty takes the reader's choice
    [row] = fp.plan_rows(engine)
    assert row["project"] == "Beta"


def test_only_queued_items_can_be_proposed(env):
    engine, settings, ids = env
    filing_queue.dequeue(engine, ids[0])
    assert propose(engine, settings, ids[0])["error"] == "not_queued"


def test_approve_and_strike_in_one_submit(env):
    engine, settings, (one, two, three) = env
    for item_id in (one, two, three):
        propose(engine, settings, item_id)
    rows = {r["item_id"]: r["id"] for r in fp.plan_rows(engine)}
    result = fp.decide(engine, approved=[rows[one], rows[two]], struck=[rows[three]], now=NOW)
    assert result == {"approved": 2, "struck": 1}
    assert [r["item_id"] for r in fp.approved_rows(engine)] == [one, two]
    # A struck row leaves the plan and the queue; the item can be queued again later.
    assert [e.item_id for e in filing_queue.waiting(engine)] == [one, two]
    assert fp.unplanned_ids(engine) == []


def test_deciding_on_unknown_or_overlapping_rows_changes_nothing(env):
    engine, settings, (one, two, _three) = env
    propose(engine, settings, one)
    propose(engine, settings, two)
    first, second = (r["id"] for r in fp.plan_rows(engine))
    with pytest.raises(ValueError, match="both approved and struck"):
        fp.decide(engine, approved=[first], struck=[first], now=NOW)
    with pytest.raises(ValueError, match="no longer waiting"):
        fp.decide(engine, approved=[first, 4242], struck=[], now=NOW)
    assert all(r["decision"] == "pending" for r in fp.plan_rows(engine))


def test_unplanned_ids_are_the_queued_items_without_a_row(env):
    engine, settings, (one, two, three) = env
    propose(engine, settings, two)
    assert fp.unplanned_ids(engine) == [one, three]


def test_filing_an_item_removes_its_row(env, tmp_path):
    engine, settings, (one, _two, _three) = env
    propose(engine, settings, one)
    note = tmp_path / "vault" / "03 RESOURCES" / "Note.md"
    note.parent.mkdir(parents=True)
    note.write_text("x", encoding="utf-8")
    assert record_filed(engine, settings, one, "03 RESOURCES/Note.md")["recorded"] is True
    assert fp.plan_rows(engine) == []


def test_changing_the_choices_drops_a_stale_row(env):
    engine, settings, (one, _two, _three) = env
    propose(engine, settings, one)
    filing_queue.enqueue(engine, one, kind="learning")
    assert fp.plan_rows(engine) == []
