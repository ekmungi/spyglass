"""What a filing session sees of the "To file" queue (the `radar_filing_queue` tool).

For each waiting item: its number, date and section, the kind, project and note the reader chose,
and one marked block holding everything that came from the web or from a model (headline, title,
address, publication, why it matters, key points, named organisations and the reader's
questions with the assistant's answers). The block is built with the same fence as
`radar_get_item`, so web text is material, never instructions. The full article text is NOT
here; the session reads it with `radar_get_item` only when the summary is not enough.

A background run passes its token and gets only its own items, plus what it needs besides: the
run's kind and mode, the reader's project list, the answered questions to apply (file runs) and,
for each item of a plan the reader approved, the approved row (inside the item's block, since a
model wrote it from web material).
"""

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.radar.filing_config import skill_names
from spyglass_service.radar.filing_plan import approved_rows
from spyglass_service.radar.filing_questions import answered_unapplied
from spyglass_service.radar.filing_queue import QueueEntry, waiting
from spyglass_service.radar.mcp_fence import NOTICE, date_text, fence, material_text, one_line, token
from spyglass_service.radar.mcp_views import item_block
from spyglass_service.radar.projects import project_directory
from spyglass_service.radar.serialize import radar_items
from spyglass_service.radar.thread_qa import CUT_NOTE, QA_MAX, item_qa_text

MAX_ITEMS = 40
KEY_POINTS_MAX = 12
ENTITIES_MAX = 12
PROJECTS_NOTE = ("The reader's project names (from the vault's projects folder) with the one-line "
                 "description the reader wrote, if any. Suggest only these names.")


def _extra_lines(item: dict, qa: str, approved: dict | None) -> list[str | None]:
    """The block lines after the common fields: why, key points, organisations, conversation."""
    lines: list[str | None] = []
    why = one_line(item.get("why"), 600)
    lines.append(f"Why it matters: {why}" if why else None)
    points = [one_line(p, 400) for p in (item.get("key_points") or [])[:KEY_POINTS_MAX]
              if isinstance(p, str)]
    if any(points):
        lines += ["Key points:", *(f"- {p}" for p in points if p)]
    names = [one_line(e, 120) for e in (item.get("entities") or [])[:ENTITIES_MAX]
             if isinstance(e, str)]
    if any(names):
        lines.append("Organisations named: " + "; ".join(n for n in names if n))
    if approved:
        lines += ["Approved plan row (the reader approved this; file it so):",
                  f"- becomes: {one_line(approved['becomes'], 80)}",
                  f"- folder: {one_line(approved['place'], 300)}",
                  f"- name: {one_line(approved['name'], 160)}",
                  f"- project: {one_line(approved['project'], 80) or 'none'}"]
    if qa:
        # Control characters become spaces and the cut comes before the fence check.
        text = material_text(qa, QA_MAX + len(CUT_NOTE))
        lines.append(f"\nMy questions and the assistant's answers:\n{text}")
    return lines


def _view(entry: QueueEntry, item: dict, qa: str, approved: dict | None = None) -> dict:
    """One queue entry for the session; web and model text sits inside `material`."""
    return {
        "id": item["id"],
        "published_at": date_text(item.get("published_at")),
        "kind": entry.kind,
        "project": one_line(entry.project, 80) or None,
        "note": one_line(entry.note, 500) or None,
        "section": token(item.get("section")),
        "material": item_block(item["id"], item, extra=_extra_lines(item, qa, approved)),
    }


def _answers(engine: Engine) -> list[dict]:
    """Answered questions to apply; the note path came from a session, so it sits in a block."""
    out = []
    for answer in answered_unapplied(engine):
        if not answer["note_path"]:
            continue
        out.append({"item_id": answer["item_id"], "project": one_line(answer["project"], 80),
                    "material": fence(f'item="{int(answer["item_id"])}"',
                                      f"Filed note: {one_line(answer['note_path'], 500)}")})
    return out


def _projects(engine: Engine, settings) -> list[dict]:
    """The reader's project names with their own one-line descriptions."""
    with Session(engine) as session:
        return [{"name": one_line(p["name"], 80), "description": one_line(p["description"], 200)}
                for p in project_directory(session, settings)]


def filing_queue_view(engine: Engine, settings=None, run: dict | None = None) -> dict:
    """The waiting items, oldest first, at most 40 per call, with a `remaining` count.

    `kind` is one of the four fixed kinds; `project` and `note` are the reader's own words
    (cleaned to one line). Items that were filed or deleted meanwhile are not listed. With `run`
    (the status of the background run in progress) only that run's items are listed, and the
    run's facts, the project list and (for a filing run) the answers to apply are added.
    """
    entries = waiting(engine)
    if run is not None:
        wanted = set(run.get("item_ids") or [])
        entries = [e for e in entries if e.item_id in wanted]
    shown = entries[:MAX_ITEMS]
    approved = {r["item_id"]: r for r in approved_rows(engine)} if run else {}
    with Session(engine) as session:
        items = {i["id"]: i for i in radar_items(session, [e.item_id for e in shown])}
    views = [_view(e, items[e.item_id], item_qa_text(engine, e.item_id, QA_MAX),
                   approved.get(e.item_id) if run and run.get("mode") == "plan_first" else None)
             for e in shown if e.item_id in items]
    body = {"notice": NOTICE, "count": len(entries), "shown": len(views),
            "remaining": len(entries) - len(shown), "items": views,
            "skills": skill_names(settings)}
    if run is None:
        return {**body, "run": None}
    extra: dict = {"run": {"id": run["run_id"], "kind": run["kind"], "mode": run["mode"]},
                   "projects_note": PROJECTS_NOTE, "projects": _projects(engine, settings)}
    if run["kind"] == "file":
        extra["answers"] = _answers(engine)
    return {**body, **extra}
