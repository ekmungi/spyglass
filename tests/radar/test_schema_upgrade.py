"""An existing database whose radar tables predate the newer columns is upgraded in place."""

from sqlalchemy import text
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db

# The radar tables as the first release created them (only the columns this test needs).
_OLD_TABLES = (
    "CREATE TABLE assessment (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE, "
    "stage VARCHAR NOT NULL DEFAULT 'triage', score INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE itemstate (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE, "
    "from_user BOOLEAN NOT NULL DEFAULT 0)",
    "CREATE TABLE radarbrief (id INTEGER PRIMARY KEY, day VARCHAR NOT NULL UNIQUE, "
    "doc VARCHAR NOT NULL, created_at DATETIME)",
    "CREATE TABLE watchentity (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL UNIQUE, "
    "status VARCHAR NOT NULL DEFAULT 'suggested')",
)


def _columns(engine, table: str) -> set[str]:
    """Column names of a table."""
    with Session(engine) as session:
        return {row[1] for row in session.exec(text(f"PRAGMA table_info({table})")).all()}


def test_old_radar_tables_gain_the_new_columns_and_keep_their_rows(tmp_path) -> None:
    """init_db adds the attempt counters, the error text, captured_at and regenerated_at."""
    engine = create_db_engine(tmp_path / "old.db")
    try:
        with Session(engine) as session:
            for ddl in _OLD_TABLES:
                session.exec(text(ddl))
            session.exec(text("INSERT INTO assessment (item_id, stage, score) VALUES (1, 'triage', 40)"))
            session.commit()
        init_db(engine)
        init_db(engine)  # a second start changes nothing and does not fail
        assert {"digest_attempts", "triage_attempts", "error"} <= _columns(engine, "assessment")
        assert "captured_at" in _columns(engine, "itemstate")
        assert "regenerated_at" in _columns(engine, "radarbrief")
        with Session(engine) as session:
            row = session.exec(text(
                "SELECT score, digest_attempts, triage_attempts, error FROM assessment")).one()
        assert tuple(row) == (40, 0, 0, None)
    finally:
        engine.dispose()


def test_old_watch_tables_gain_section_and_count(tmp_path) -> None:
    """init_db adds the section and the suggestion count, and an old row reads as no section, count 0."""
    engine = create_db_engine(tmp_path / "old.db")
    try:
        with Session(engine) as session:
            for ddl in _OLD_TABLES:
                session.exec(text(ddl))
            session.exec(text("INSERT INTO watchentity (name, status) VALUES ('Alpha Scopes', 'active')"))
            session.commit()
        init_db(engine)
        init_db(engine)
        assert {"section", "suggest_count"} <= _columns(engine, "watchentity")
        with Session(engine) as session:
            row = session.exec(text("SELECT status, section, suggest_count FROM watchentity")).one()
        assert tuple(row) == ("active", "", 0)
    finally:
        engine.dispose()
