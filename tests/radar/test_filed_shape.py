"""Tests for the filed information in the item shape and the feed condition that finds filed items."""

import pytest
from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.filed import filed_condition
from spyglass_service.radar.models import ItemExtra, dumps
from spyglass_service.radar.serialize import radar_items


@pytest.fixture
def db(tmp_path):
    """A database with three items: filed, with other extra facts only, and with a bad entry."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as session:
        items = [Item(source="rss", external_id=f"e{n}", title=f"T{n}", url=f"https://x.example/{n}")
                 for n in range(4)]
        session.add_all(items)
        session.commit()
        filed = {"path": "01 PROJECTS/A/Note.md", "project": "A", "at": "2026-11-12T10:00:00"}
        session.add(ItemExtra(item_id=items[0].id, data=dumps({"filed": filed, "points": 3})))
        session.add(ItemExtra(item_id=items[1].id, data=dumps({"points": 9})))
        session.add(ItemExtra(item_id=items[2].id, data=dumps({"filed": "not an object"})))
        session.commit()
    yield engine
    engine.dispose()


def test_radar_items_carry_the_filed_object_or_null(db):
    with Session(db) as session:
        out = {i["id"]: i for i in radar_items(session, [1, 2, 3, 4])}
    assert out[1]["filed"] == {"path": "01 PROJECTS/A/Note.md", "project": "A",
                               "at": "2026-11-12T10:00:00"}
    assert out[2]["filed"] is None and out[3]["filed"] is None and out[4]["filed"] is None


def test_filed_condition_selects_only_items_with_a_filing_path(db):
    with Session(db) as session:
        ids = session.exec(select(Item.id).where(filed_condition())).all()
    assert list(ids) == [1]
