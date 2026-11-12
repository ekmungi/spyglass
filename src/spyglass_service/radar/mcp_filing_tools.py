"""MCP tools only a background filing run may use: ask, propose, report and mark an answer applied.

Each takes the run's token from the request the run started with; a call without the token of
the run in progress is refused (`not_running`), so another session cannot speak for a run. What
a tool call supplies is checked and cleaned before it is stored (one plain line, length caps, no
markup), because the interface shows it. Registered from `mcp_tools.register_radar_tools`.
"""

from fastmcp import FastMCP

from spyglass_service.radar import filing_plan, filing_questions, filing_status

NOT_RUNNING = {"error": "not_running",
               "detail": "No background filing run with that token is in progress."}


def _run(state, run_id: object, kind: str | None = None) -> dict | None:
    """The run in progress for this token (and of this kind, when given), else None."""
    run = filing_status.current_run(state.engine, run_id)
    if run is None or (kind is not None and run["kind"] != kind):
        return None
    return run


def register_filing_tools(mcp: FastMCP, state) -> None:
    """Add the background-run tools to `mcp`; `state` supplies `engine` and `settings`."""

    @mcp.tool
    def radar_filing_ask(run_id: str, item_id: int, options: list[str]) -> dict:
        """Background filing runs only. After filing an item for which the reader chose no
        project, leave the one question Spyglass allows: "Link this to a project?". `options` are
        one to three of the reader's project names from radar_filing_queue's `projects`; Spyglass
        adds "No project" and fixes the wording. Never ask anything else."""
        run = _run(state, run_id, "file")
        if run is None:
            return NOT_RUNNING
        if item_id not in (run.get("item_ids") or []):
            return {"error": "not_in_run", "detail": "Ask only about an item of this run."}
        return filing_questions.ask(state.engine, state.settings, item_id, options)

    @mcp.tool
    def radar_filing_propose(run_id: str, item_id: int, becomes: str, place: str, name: str,
                             project: str | None = None, unsure: bool = False,
                             reason: str = "") -> dict:
        """Plan-first runs only. Record what a queued item would become (for example "resource
        note"), the folder relative to the vault where the vault skills would put it, the note's
        name, the project (the reader's choice when they made one, else one of the listed
        names or none), whether you are unsure, and why in one short sentence. Writes nothing
        into the vault."""
        run = _run(state, run_id, "plan")
        if run is None:
            return NOT_RUNNING
        if item_id not in (run.get("item_ids") or []):
            return {"error": "not_in_run", "detail": "Propose only for an item of this run."}
        return filing_plan.propose(state.engine, state.settings, item_id, becomes=becomes,
                                   place=place, name=name, project=project, unsure=unsure,
                                   reason=reason)

    @mcp.tool
    def radar_filing_report(run_id: str, status: str, reason: str | None = None,
                            detail: str = "") -> dict:
        """Background filing runs only. Say how the run ended, once, as the last call: status
        "done", or "stopped" with reason "skills_missing", "tools_missing",
        "obsidian_unreachable" or "failed", and at most one short sentence of detail."""
        return filing_status.record_report(state.engine, run_id, status, reason, detail)

    @mcp.tool
    def radar_filing_applied(run_id: str, item_id: int) -> dict:
        """Background filing runs only. After linking a filed item to the project the reader
        chose in answer to "Link this to a project?", record that the answer was applied."""
        if _run(state, run_id, "file") is None:
            return NOT_RUNNING
        return filing_questions.mark_applied(state.engine, item_id)
