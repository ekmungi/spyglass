"""The MCP tools a background job's Claude run uses to start, save, file and report.

They act only on a running job, and only in the way its kind allows: a prepare-detail run saves
one note through Spyglass; a filing run names a folder, and Spyglass itself checks it and has
Obsidian move the job's note there, so the run holds no Obsidian tool of its own.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import Session

from spyglass_service import claude_jobs as jobs
from spyglass_service.detail_notes import (
    folder_names,
    in_spyglass_folder,
    vault_relative,
    write_detail_note,
)
from spyglass_service.filing import check_filing_folder
from spyglass_service.job_prompts import instructions
from spyglass_service.mcp_items import item_view
from spyglass_service.models import Card, ClaudeJob
from spyglass_service.obsidian_move import ObsidianMoveError

MESSAGE_MAX = 300


def _running(state, job_id: int, kind: str | None = None) -> ClaudeJob | dict:
    job = jobs.get_job(state.engine, int(job_id))
    if job is None:
        return {"error": "unknown_job", "detail": f"No Spyglass job {job_id}."}
    if job.status != "running":
        return {"error": "not_running", "detail": f"Job {job_id} is {job.status}."}
    # The job stays "running" until the run's process ends, but its outcome is settled once it
    # has reported: nothing may move a note or overwrite that outcome afterwards.
    if job.reported:
        return {"error": "already_reported",
                "detail": f"Job {job_id} has already reported its outcome. Stop here."}
    if kind is not None and job.kind != kind:
        return {"error": "wrong_kind", "detail": f"Job {job_id} is a {job.kind} job."}
    return job


def job_instructions(state, job: ClaudeJob) -> str:
    settings = state.settings
    with Session(state.engine) as session:
        card = session.get(Card, job.card_id)
        note = vault_relative(settings, card.briefing_path) if card else None
    return instructions(job.kind, note_path=note, spyglass_folders=folder_names(settings))


def _job_note(state, job: ClaudeJob) -> Path | None:
    """The note of the job's item, where the card says it is."""
    with Session(state.engine) as session:
        card = session.get(Card, job.card_id)
        return Path(card.briefing_path) if card and card.briefing_path else None


def register_job_tools(mcp: FastMCP, state) -> None:
    """job_start, job_save_detail, job_file_note and job_finish."""

    @mcp.tool
    def job_start(job_id: int) -> dict:
        """Start a Spyglass background job: returns its item and the instructions to follow."""
        job = _running(state, job_id)
        if isinstance(job, dict):
            return job
        jobs.set_progress(state.engine, job.id, "Claude is working")
        return {"job_id": job.id, "kind": job.kind, "item": item_view(state.engine, job.card_id),
                "instructions": job_instructions(state, job)}

    @mcp.tool
    def job_save_detail(job_id: int, title: str, markdown: str) -> dict:
        """Save the detailed note a prepare-detail job wrote (Markdown body, no frontmatter).
        Spyglass writes the file in the dated Brief notes folder and returns its path."""
        job = _running(state, job_id, jobs.PREPARE)
        if isinstance(job, dict):
            return job
        if not markdown.strip():
            return {"error": "empty_note", "detail": "The note has no text."}
        path = write_detail_note(state.settings, state.engine, job.card_id,
                                 title.strip() or "Spyglass item", markdown)
        rel = vault_relative(state.settings, str(path))
        with Session(state.engine) as session:
            row = session.get(ClaudeJob, job.id)
            row.note_path = rel
            session.add(row)
            session.commit()
        return {"saved": True, "path": rel}

    @mcp.tool
    async def job_file_note(job_id: int, folder: str) -> dict:
        """Move this filing job's note into `folder`: an existing vault folder, written relative to
        the vault root (for example "01 PROJECTS/Name"). Spyglass checks the folder, has Obsidian
        move the note, and checks that it arrived. Returns the note's new path, or an error whose
        detail says what to change. This is the only way a filing run moves a file."""
        job = _running(state, job_id, jobs.FILE)
        if isinstance(job, dict):
            return job
        settings = state.settings
        note = _job_note(state, job)
        if note is None or not note.is_file():
            return {"error": "no_note", "detail": "This item has no note to file."}
        if not in_spyglass_folder(settings, note):
            return {"error": "already_filed",
                    "detail": f"The note is already filed at {vault_relative(settings, str(note))}."}
        target, problem = check_filing_folder(settings, folder)
        if problem is not None:
            return {"error": "bad_folder", "detail": problem}
        wanted = vault_relative(settings, str(target))
        destination = target / note.name
        if destination.exists():
            return {"error": "name_taken",
                    "detail": f"A note named {note.name} is already in {wanted}. Choose another "
                              "folder, or report that the note could not be filed."}
        failure = None
        try:
            await state.obsidian_move(settings, vault_relative(settings, str(note)), f"{wanted}/")
        except ObsidianMoveError as exc:
            failure = {"error": "move_failed", "detail": str(exc)}
        # Only the vault says whether the note moved: an error can arrive after the move (a late
        # answer), and a "done" can arrive without one. Moved means here and gone from there.
        if not destination.is_file() or note.exists():
            return failure or {
                "error": "not_filed",
                "detail": f"Obsidian answered, but the note is not in {wanted}, so it was not filed."}
        new_path = vault_relative(settings, str(destination))
        with Session(state.engine) as session:
            row = session.get(ClaudeJob, job.id)
            row.note_path = new_path
            session.add(row)
            card = session.get(Card, job.card_id)
            if card is not None:
                card.briefing_path = str(destination)
                card.updated_at = datetime.now(UTC)
                session.add(card)
            session.commit()
        return {"moved": True, "path": new_path}

    @mcp.tool
    def job_finish(job_id: int, ok: bool, message: str, note_path: str | None = None) -> dict:
        """Report the job's outcome: ok with a one-line message, or not ok with the reason. A
        filing job passes nothing else: Spyglass recorded the move itself (`note_path` is
        ignored)."""
        job = _running(state, job_id)
        if isinstance(job, dict):
            return job
        message = " ".join(message.split())[:MESSAGE_MAX]
        error = None if ok else (message or "Claude could not finish the job.")
        if ok and job.kind == jobs.PREPARE and not job.note_path:
            error = "Claude reported success but never saved the note."
        if ok and job.kind == jobs.FILE:
            error = _unbelieved_filing(state, job)
        with Session(state.engine) as session:
            row = session.get(ClaudeJob, job.id)
            row.reported = True
            row.message = message
            row.error = error
            session.add(row)
            session.commit()
        return {"recorded": True, "ok": error is None, **({"error": error} if error else {})}


def _unbelieved_filing(state, job: ClaudeJob) -> str | None:
    """Why Spyglass does not believe a filing job's success, or None. It believes only its own
    move (`job_file_note`), which records the note's new path on the job; a note the user moved
    by hand while the job waited is not a filing this run made."""
    if not job.note_path:
        return "Claude reported filing the note, but Spyglass made no move for this job."
    note = _job_note(state, job)
    if note is None or not note.is_file():
        return "Claude reported filing the note, but Spyglass has no note for this item."
    if in_spyglass_folder(state.settings, note):
        return ("Claude reported filing the note, but Spyglass made no move: the note is still in "
                "one of Spyglass's own folders.")
    return None
