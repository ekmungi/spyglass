"""Tests for the reader-controlled project directory (radar/projects.py)."""

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar.models import RadarDoc, loads
from spyglass_service.radar.projects import (
    DOC_KEY,
    described_projects,
    project_directory,
    project_from_note,
    save_project_directory,
    vault_project_names,
)


@pytest.fixture
def db(tmp_path):
    """A fresh database, disposed afterwards."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine
    engine.dispose()


def make_vault(tmp_path, folders=("Alpha", "Beta Project", ".hidden")) -> Settings:
    """A vault with a projects folder holding `folders`, plus notes that must never be read."""
    vault = tmp_path / "vault"
    projects = vault / "01 PROJECTS"
    for name in folders:
        (projects / name).mkdir(parents=True)
    (projects / "Alpha" / "secret.md").write_text("confidential", encoding="utf-8")
    (projects / "loose-note.md").write_text("not a folder", encoding="utf-8")
    (vault / "02 AREAS" / "Other").mkdir(parents=True)
    return Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)


def test_vault_project_names_lists_folder_names_only(tmp_path):
    assert vault_project_names(make_vault(tmp_path)) == ["Alpha", "Beta Project"]


def test_vault_project_names_is_empty_without_a_vault_or_projects_folder(tmp_path):
    assert vault_project_names(Settings(_env_file=None, data_dir=tmp_path, vault_path=None)) == []
    bare = tmp_path / "bare"
    (bare / "Notes").mkdir(parents=True)
    assert vault_project_names(Settings(_env_file=None, data_dir=tmp_path, vault_path=bare)) == []
    missing = Settings(_env_file=None, data_dir=tmp_path, vault_path=tmp_path / "nope")
    assert vault_project_names(missing) == []


def test_directory_merges_vault_names_with_stored_descriptions(tmp_path, db):
    settings = make_vault(tmp_path)
    with Session(db) as session:
        save_project_directory(session, [
            {"name": "Alpha", "description": "Imaging research"},
            {"name": "Gone", "description": "An old project whose folder was removed"},
        ])
        rows = project_directory(session, settings)
    assert rows == [
        {"name": "Alpha", "description": "Imaging research", "in_vault": True},
        {"name": "Beta Project", "description": "", "in_vault": True},
        {"name": "Gone", "description": "An old project whose folder was removed",
         "in_vault": False},
    ]


def test_save_cleans_text_and_drops_entries_without_a_description(db):
    with Session(db) as session:
        saved = save_project_directory(session, [
            {"name": "  Alpha‮  ", "description": "line one\nline\ttwo\x07"},
            {"name": "Beta", "description": "   "},
        ])
        stored = loads(session.get(RadarDoc, DOC_KEY).body, [])
    assert saved == [{"name": "Alpha", "description": "line one line two"}]
    assert stored == saved


@pytest.mark.parametrize("entries", [
    [{"name": "x" * 81, "description": "d"}],
    [{"name": "ok", "description": "d" * 201}],
    [{"name": "", "description": "d"}],
    [{"name": "Same", "description": "a"}, {"name": "same", "description": "b"}],
    [{"name": f"p{n}", "description": "d"} for n in range(101)],
    [{"name": 3, "description": "d"}],
    "not a list",
])
def test_save_refuses_invalid_directories(db, entries):
    with Session(db) as session:
        with pytest.raises(ValueError):
            save_project_directory(session, entries)
        assert session.get(RadarDoc, DOC_KEY) is None


def test_described_projects_returns_only_entries_with_descriptions(db):
    with Session(db) as session:
        assert described_projects(session) == []
        save_project_directory(session, [{"name": "Alpha", "description": "Imaging"},
                                         {"name": "Beta", "description": ""}])
        assert described_projects(session) == [{"name": "Alpha", "description": "Imaging"}]


def test_described_projects_survives_a_corrupt_document(db):
    with Session(db) as session:
        session.add(RadarDoc(key=DOC_KEY, body="{broken"))
        session.commit()
        assert described_projects(session) == []


@pytest.mark.parametrize("note, expected", [
    ("useful for alpha later", "Alpha"),
    ("see Beta Project and Alpha", "Beta Project"),  # the longest name that matches wins
    ("alphabet soup", None),
    ("for the AI work", "AI"),
    ("said ai once", None),  # a short name needs its exact case
    ("", None),
    (None, None),
])
def test_project_from_note(note, expected):
    assert project_from_note(note, ["Alpha", "Beta Project", "AI", "Beta"]) == expected
