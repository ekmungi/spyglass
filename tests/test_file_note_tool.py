"""Tests for job_file_note: Spyglass moves a filing job's note itself.

The run names only a folder. Spyglass takes the note from the job, checks the folder, asks
Obsidian to move that one note (without overwriting), and checks that it arrived.
"""

import asyncio
import os
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from fastmcp import Client
from sqlmodel import Session

from spyglass_service import claude_jobs as jobs
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.detail_notes import write_detail_note
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.models import Card, ClaudeJob, Item

NOTE = "Optogenetics, explained"


@pytest.fixture
def state(tmp_path: Path, fake_obsidian) -> ServiceState:
    vault = tmp_path / "Vault"
    vault.mkdir()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    st = ServiceState(settings=settings, engine=engine)
    st.obsidian_move = fake_obsidian
    return st


def call(state: ServiceState, tool: str, args: dict) -> dict:
    async def go():
        async with Client(build_mcp(state)) as client:
            result = await client.call_tool(tool, args)
            return result.structured_content
    return asyncio.run(go())


def make_folder(state: ServiceState, name: str) -> Path:
    path = state.settings.vault_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def running_job(state: ServiceState, kind: str = jobs.FILE) -> tuple[int, int, Path]:
    """A running job for a card whose note sits in today's Brief notes folder:
    (job id, card id, note path)."""
    with Session(state.engine) as session:
        item = Item(source="rss", external_id="x", title=NOTE, url="https://x.test/a")
        session.add(item)
        session.commit()
        card = Card(item_id=item.id, summary="About it.")
        session.add(card)
        session.commit()
        card_id = card.id
    note = write_detail_note(state.settings, state.engine, card_id, NOTE, "Body",
                             today=date(2026, 10, 15))
    job, _ = jobs.enqueue(state.engine, kind, card_id)
    jobs.claim_next(state.engine)
    return job["id"], card_id, note


def relative(state: ServiceState, path: Path) -> str:
    return path.relative_to(state.settings.vault_path).as_posix()


def test_the_note_moves_into_the_folder_and_is_recorded(state: ServiceState) -> None:
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result == {"moved": True, "path": f"02 AREAS/Imaging/{NOTE}.md"}
    # Obsidian is asked to move the job's own note, keeping its name, and nothing else.
    assert state.obsidian_move.calls == [(relative(state, note), "02 AREAS/Imaging/")]
    with Session(state.engine) as session:
        card, row = session.get(Card, card_id), session.get(ClaudeJob, job_id)
    assert relative(state, Path(card.briefing_path)) == f"02 AREAS/Imaging/{NOTE}.md"
    assert row.note_path == f"02 AREAS/Imaging/{NOTE}.md"
    assert not note.exists()


BAD_FOLDERS = [
    "..", "../outside", "02 AREAS/../../outside",          # out of the vault
    "C:/Windows", "C:\\Users", "D:",                        # a drive
    "", "   ", ".", "/",                                    # no folder at all
    ".obsidian", ".trash", "02 AREAS/.hidden",              # hidden folders
    "03 RESOURCES/Spyglass", "03 RESOURCES/Spyglass/Brief notes",
    "03 RESOURCES/Spyglass/Brief notes/2026-10-15",         # Spyglass's own folders and inside them
    "03 RESOURCES/Research/Spyglass", "03 RESOURCES/Research/Spyglass/papers",
    "No/Such/Folder", "02 AREAS/notes.md",                  # missing, or a file
    "02 AREAS/a|b", "02 AREAS/what?", "02 AREAS/a:b",       # characters Windows refuses
]


@pytest.mark.parametrize("folder", BAD_FOLDERS)
def test_a_folder_that_is_not_safe_is_refused_and_nothing_moves(
        state: ServiceState, folder: str) -> None:
    job_id, _card, note = running_job(state)
    for name in ("02 AREAS/Imaging", ".obsidian", ".trash", "02 AREAS/.hidden",
                 "03 RESOURCES/Research/Spyglass/papers"):
        make_folder(state, name)
    (state.settings.vault_path / "02 AREAS" / "notes.md").write_text("a note")
    result = call(state, "job_file_note", {"job_id": job_id, "folder": folder})
    assert result["error"] == "bad_folder" and result["detail"]
    assert state.obsidian_move.calls == []
    assert note.is_file()


@contextmanager
def folder_link(target: Path, link: Path):
    """A folder link made the way an ordinary user can: a junction on Windows, which needs no
    admin rights (a symbolic link does), and a symbolic link elsewhere. Removed afterwards, so
    the test folder's clean-up never follows it."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)
    try:
        yield link
    finally:
        os.rmdir(link) if sys.platform == "win32" else os.unlink(link)


def test_a_link_that_leaves_the_vault_is_refused(state: ServiceState, tmp_path: Path) -> None:
    job_id, _card, note = running_job(state)
    outside = tmp_path / "Elsewhere"
    outside.mkdir()
    with folder_link(outside, state.settings.vault_path / "02 AREAS" / "Linked"):
        result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Linked"})
    assert result["error"] == "bad_folder"
    assert state.obsidian_move.calls == [] and note.is_file()


def test_a_link_to_the_vault_root_is_refused(state: ServiceState) -> None:
    """The root check must look at where a folder leads, not only at how it is written."""
    job_id, _card, note = running_job(state)
    vault = state.settings.vault_path
    with folder_link(vault, vault / "02 AREAS" / "Root"):
        result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Root"})
    assert result["error"] == "bad_folder"
    assert state.obsidian_move.calls == [] and note.is_file()


def test_a_name_already_taken_is_refused_without_asking_obsidian(state: ServiceState) -> None:
    job_id, _card, note = running_job(state)
    (make_folder(state, "02 AREAS/Imaging") / f"{NOTE}.md").write_text("someone else's note")
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result["error"] == "name_taken" and NOTE in result["detail"]
    assert state.obsidian_move.calls == [] and note.is_file()
    assert (state.settings.vault_path / "02 AREAS/Imaging" / f"{NOTE}.md").read_text() == \
        "someone else's note"


def test_obsidian_failing_leaves_the_note_and_says_why(state: ServiceState) -> None:
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    state.obsidian_move.error = "Obsidian did not answer"
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result["error"] == "move_failed" and "Obsidian did not answer" in result["detail"]
    assert note.is_file()
    with Session(state.engine) as session:
        assert Path(session.get(Card, card_id).briefing_path) == note


def test_a_move_that_succeeded_before_an_error_is_recorded(state: ServiceState) -> None:
    """Obsidian can move the note and then fail to answer in time; the vault, not the error,
    says what happened, so the item must not be left pointing at a file that is gone."""
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    state.obsidian_move.error_after_move = "Obsidian did not answer within 30 seconds"
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    moved = state.settings.vault_path / "02 AREAS/Imaging" / f"{NOTE}.md"
    assert result == {"moved": True, "path": f"02 AREAS/Imaging/{NOTE}.md"}
    assert moved.is_file() and not note.exists()
    with Session(state.engine) as session:
        assert Path(session.get(Card, card_id).briefing_path) == moved
        assert session.get(ClaudeJob, job_id).note_path == f"02 AREAS/Imaging/{NOTE}.md"


def test_obsidian_copying_instead_of_moving_is_not_believed(state: ServiceState) -> None:
    """A copy leaves the original behind; only a real move counts as filed."""
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    state.obsidian_move.copies = True
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result["error"] == "not_filed"
    with Session(state.engine) as session:
        assert Path(session.get(Card, card_id).briefing_path) == note
        assert session.get(ClaudeJob, job_id).note_path is None


def test_obsidian_saying_ok_without_moving_is_not_believed(state: ServiceState) -> None:
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    state.obsidian_move.moves = False
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result["error"] == "not_filed"
    with Session(state.engine) as session:
        assert Path(session.get(Card, card_id).briefing_path) == note


def test_a_note_is_moved_only_once(state: ServiceState) -> None:
    job_id, _card, _note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    make_folder(state, "01 PROJECTS/Optics")
    assert call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})["moved"]
    again = call(state, "job_file_note", {"job_id": job_id, "folder": "01 PROJECTS/Optics"})
    assert again["error"] == "already_filed" and "02 AREAS/Imaging" in again["detail"]
    assert len(state.obsidian_move.calls) == 1


def test_an_item_with_no_note_has_nothing_to_move(state: ServiceState) -> None:
    job_id, card_id, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    with Session(state.engine) as session:
        card = session.get(Card, card_id)
        card.briefing_path = None
        session.add(card)
        session.commit()
    result = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    assert result["error"] == "no_note"
    assert state.obsidian_move.calls == [] and note.is_file()


def test_a_filing_is_believed_only_when_spyglass_moved_the_note(state: ServiceState) -> None:
    """A note the user moved by hand while the job waited is not a filing this run made."""
    job_id, card_id, note = running_job(state)
    by_hand = make_folder(state, "02 AREAS/Imaging") / note.name
    os.replace(note, by_hand)
    with Session(state.engine) as session:
        card = session.get(Card, card_id)
        card.briefing_path = str(by_hand)
        session.add(card)
        session.commit()
    result = call(state, "job_finish", {"job_id": job_id, "ok": True, "message": "Filed it."})
    assert result["ok"] is False and "made no move" in result["error"]


def test_a_job_that_has_reported_cannot_act_again(state: ServiceState) -> None:
    """After job_finish the outcome is settled: the run can no longer move the note or report
    a second outcome over the first."""
    job_id, _card, note = running_job(state)
    make_folder(state, "02 AREAS/Imaging")
    call(state, "job_finish", {"job_id": job_id, "ok": False, "message": "Could not decide."})
    moved = call(state, "job_file_note", {"job_id": job_id, "folder": "02 AREAS/Imaging"})
    again = call(state, "job_finish", {"job_id": job_id, "ok": True, "message": "Filed after all."})
    assert moved["error"] == "already_reported" and again["error"] == "already_reported"
    assert state.obsidian_move.calls == [] and note.is_file()
    with Session(state.engine) as session:
        assert session.get(ClaudeJob, job_id).message == "Could not decide."


def test_only_a_running_filing_job_may_move_a_note(state: ServiceState) -> None:
    make_folder(state, "02 AREAS/Imaging")
    args = {"folder": "02 AREAS/Imaging"}
    assert call(state, "job_file_note", {"job_id": 999, **args})["error"] == "unknown_job"
    prepare_id, _card, _note = running_job(state, jobs.PREPARE)
    assert call(state, "job_file_note", {"job_id": prepare_id, **args})["error"] == "wrong_kind"
    with Session(state.engine) as session:
        card = Card(item_id=session.get(Card, 1).item_id, summary="Another.")
        session.add(card)
        session.commit()
        queued, _ = jobs.enqueue(state.engine, jobs.FILE, card.id)
    assert call(state, "job_file_note", {"job_id": queued["id"], **args})["error"] == "not_running"
    assert state.obsidian_move.calls == []
