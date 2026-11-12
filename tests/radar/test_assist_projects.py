# ruff: noqa: F811
"""Tests for the assistant's view of the reader's projects: the prompt block and the preset."""

import sys

from spyglass_service.radar import projects
from spyglass_service.radar.assist import context

from .test_assist_support import clean_assist_env, db  # noqa: F401

HEADER = "The reader's projects (use these names exactly; never invent a project):"


def _described(monkeypatch, entries: list[dict]) -> None:
    """Make the reader's described projects exactly `entries`."""
    monkeypatch.setattr(projects, "described_projects", lambda _session: entries)


def test_the_system_prompt_lists_described_projects_after_the_profile(db, monkeypatch) -> None:
    _described(monkeypatch, [{"name": "Atlas", "description": "A polyp detector"},
                             {"name": "Beacon", "description": "Edge\nreview tool"}])
    system = context.build_system(db)
    assert HEADER in system
    assert "- Atlas: A polyp detector\n- Beacon: Edge review tool" in system
    assert system.index("About the reader") < system.index(HEADER)


def test_no_block_when_no_project_is_described(db, monkeypatch) -> None:
    _described(monkeypatch, [])
    assert HEADER not in context.build_system(db)


def test_a_missing_projects_module_means_no_projects(db, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.projects", None)
    assert HEADER not in context.build_system(db)


def test_the_list_is_capped_by_count_and_by_characters(db, monkeypatch) -> None:
    many = [{"name": f"P{i}", "description": "d"} for i in range(60)]
    _described(monkeypatch, many)
    with_cap = context.build_system(db)
    assert with_cap.count("\n- P") == context.PROJECTS_MAX and "P40:" not in with_cap
    _described(monkeypatch, [{"name": f"P{i}", "description": "word " * 100} for i in range(20)])
    block = next(p for p in context.build_system(db).split("\n\n") if p.startswith(HEADER))
    assert len(block) - len(HEADER) <= context.PROJECTS_CHARS + 2


def test_entries_without_a_name_or_description_are_skipped(db, monkeypatch) -> None:
    _described(monkeypatch, [{"name": "", "description": "x"}, {"name": "Only", "description": " "},
                             {"name": "Kept", "description": "fine"}])
    system = context.build_system(db)
    assert "- Kept: fine" in system and "- Only" not in system


def test_the_projects_preset_exists_and_limits_itself() -> None:
    assert "projects" in context.action_names()
    turn = context.build_turn("", action="projects")
    assert "never propose more than three" in turn and "Never invent a project" in turn
    assert "no projects have been described yet" in turn and "Profile page" in turn
