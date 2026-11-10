"""Tests for the lightweight startup migration that adds missing columns."""

from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, create_engine

from spyglass_service.db import init_db


def test_adds_curated_column_to_a_pre_curated_card_table(tmp_path: Path) -> None:
    """An older DB whose card table predates the 'curated' column is upgraded in place."""
    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db}")
    # Simulate the old schema: a card table without the 'curated' column.
    with Session(engine) as session:
        session.exec(
            text(
                "CREATE TABLE card (id INTEGER PRIMARY KEY, item_id INTEGER, "
                "state VARCHAR, summary VARCHAR, tags VARCHAR, note VARCHAR, "
                "deep_dive_prompt VARCHAR, briefing_path VARCHAR, "
                "created_at VARCHAR, updated_at VARCHAR)"
            )
        )
        session.exec(
            text("INSERT INTO card (id, item_id, state, summary) VALUES (1, 1, 'new', 's')")
        )
        session.commit()

    init_db(engine)  # must add the missing column without dropping the row

    with Session(engine) as session:
        cols = [row[1] for row in session.exec(text("PRAGMA table_info(card)")).all()]
        count = session.exec(text("SELECT count(*) FROM card")).one()[0]
    assert "curated" in cols
    assert count == 1
