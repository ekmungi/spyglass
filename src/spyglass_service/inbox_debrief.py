"""The run debrief: one vault note per inbox run on how its papers connect.

Each paper's own debrief lives in its note. The run debrief is written once a run has
filed its papers: which papers overlap, how they link to what the vault already holds, and ideas
for the user's active projects. Spyglass writes it with the same atomic writer as briefings (in the
briefing folder, so it sits with Spyglass's other research notes) and keeps its path on the run, so
the Inbox tab can open it.
"""

from datetime import UTC
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.models import InboxRun
from spyglass_service.vault import save_briefing


def save_run_debrief(
    engine: Engine, settings: Settings, run_id: int, title: str, markdown: str
) -> dict:
    """Write the run debrief note and record its path on the run. Returns {path} or an error."""
    with Session(engine) as session:
        if session.get(InboxRun, run_id) is None:
            return {"error": "not_found", "detail": f"no inbox run {run_id}"}
    if settings.vault_path is None:
        return {"error": "no_vault", "detail": "vault_path is not configured"}
    path = save_briefing(settings, title, markdown)
    with Session(engine) as session:
        run = session.get(InboxRun, run_id)
        run.debrief_path = str(path)
        session.add(run)
        session.commit()
    return {"path": str(path)}


def inbox_instructions(run_id: int, skills_dir: Path) -> str:
    """The spyglass-inbox workflow, handed out by inbox_start so a session can run the inbox
    without the skill being installed in the vault (the skill sync needs a restart on the new
    version and a session opened in the vault). Empty when the skill file cannot be read."""
    try:
        text = (skills_dir / "spyglass-inbox" / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return (
        f"You have already called inbox_start: this is run {run_id}. Continue from step 2 of "
        "the workflow below (do not call inbox_start again). If the Slack connector is not "
        f"available, call inbox_finish(run_id={run_id}, ok=false, error=\"Slack is not "
        "connected\"), tell the user to connect Slack in the Claude desktop app, and stop.\n\n"
        + text.strip()
    )


def recent_debriefs(engine: Engine, limit: int = 5) -> list[dict]:
    """The latest runs that wrote a debrief, newest first, so a later empty run does not hide it."""
    with Session(engine) as session:
        runs = session.exec(
            select(InboxRun)
            .where(InboxRun.debrief_path.is_not(None))  # type: ignore[union-attr]
            .order_by(InboxRun.started_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
    return [
        {
            "run_id": run.id, "papers": run.papers, "debrief_path": run.debrief_path,
            "started_at": (run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)).isoformat(),
        }
        for run in runs
    ]
