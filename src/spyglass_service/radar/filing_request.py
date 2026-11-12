"""The one request that starts a batch filing session for everything in the "To file" queue.

The text is short and fixed in shape: how many items wait, a pointer to the `spyglass-file`
skill, the instruction to propose one table and wait for a yes, and the standing line that item
text is material from the web. It holds no article text and no item titles; the session reads
the items with the `radar_filing_queue` tool, whose result marks web text as material. Opening
reuses the per-item opener and delivery logic of `claude_bridge`. Nothing is written to the
vault here.

`build_run_request` is the matching text for a hidden background run (`filing_run`): the run's
token, its kind and counts, the tool server's name and the exact vault-tool prefix, again without
any item text.
"""

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.claude_link import HandoffStore
from spyglass_service.radar.bridge_check import service_address
from spyglass_service.radar.claude_bridge import (
    ABOUT_HINT,
    MISSING_TOOLS_BATCH,
    STANDING_LINE,
    BridgeError,
    LinkOpener,
    deliver_text,
    describe_text,
)
from spyglass_service.radar.filing_queue import count, waiting
from spyglass_service.radar.models import Signal

EMPTY_QUEUE = "Nothing is waiting to be filed."


def build_batch_request(total: int, address: str) -> str:
    """The request text for `total` queued items (at least one) sent by the Spyglass at `address`."""
    items = "1 item is" if total == 1 else f"{total} items are"
    return "\n".join([
        f"Spyglass: {items} waiting to be filed in this vault. "
        f"This comes from the Spyglass running at {address}.",
        "",
        "Please file them with the spyglass-file skill, following the vault's own rules. "
        "Read the queue with the Spyglass tool radar_filing_queue, propose one table of where "
        "each item goes, and wait for my yes before writing anything.",
        f"{MISSING_TOOLS_BATCH} {ABOUT_HINT}",
        STANDING_LINE,
    ])


def build_run_request(*, run_id: str, kind: str, mode: str, items: int, answers: int,
                      launcher: str | None, server: str) -> str:
    """The text a hidden background run starts with: its token, kind and counts, never titles.

    `launcher` is the exact command prefix of the vault tool (the only shell commands allowed);
    `server` is the name of this service's tool server in the session.
    """
    section = "Plan-first run" if kind == "plan" else "Background run"
    lines = [
        f"Spyglass background filing run {run_id}: a {'planning' if kind == 'plan' else 'filing'} "
        f"run in mode {mode}. Items in this run: {items}. Answers to apply: {answers}.",
        "",
        "Nobody is watching this run. Never ask a question in the conversation and never wait "
        f"for an answer. Follow the \"{section}\" section of the spyglass-file skill.",
        f"The Spyglass tools are on the tool server named {server}. Pass run_id \"{run_id}\" to "
        "radar_filing_queue and to every radar_filing_ tool.",
    ]
    if kind == "plan":
        lines.append("This run writes nothing into the vault: record one proposal per item "
                     "with radar_filing_propose.")
    if launcher:
        lines.append(f"Run the vault tool's look-up commands exactly as: {launcher} <command> "
                     "(other forms of the command are refused in this run).")
    lines += [STANDING_LINE, "End with radar_filing_report."]
    return "\n".join(lines)


def _request(engine: Engine, settings) -> str:
    """The batch request text for the current queue; BridgeError (409) when it is empty."""
    total = count(engine)
    if total == 0:
        raise BridgeError(409, EMPTY_QUEUE)
    return build_batch_request(total, service_address(settings))


def preview_batch(engine: Engine, settings, *, can_open: bool = True) -> dict:
    """What would be sent, where it would open and whether it can open now (as a per-item preview)."""
    return describe_text(_request(engine, settings), settings, can_open=can_open)


def open_batch(engine: Engine, settings, *, opener: LinkOpener | None,
               handoffs: HandoffStore) -> dict:
    """Open Claude Code in the vault with the batch request typed in.

    Records a "share" signal on each queued item. Raises BridgeError (409 for an empty queue, no
    vault folder or no opener) and OpenFailed when the operating system could not open it.
    """
    text = _request(engine, settings)
    delivery = deliver_text(text, settings, opener=opener, handoffs=handoffs)
    with Session(engine) as session:
        for entry in waiting(engine):
            session.add(Signal(item_id=entry.item_id, kind="share", value="claude_code:file_batch"))
        session.commit()
    return {"opened": True, "delivery": delivery}
