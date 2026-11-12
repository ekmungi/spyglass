"""The reader's questions about an item and the assistant's answers, as plain text.

An item's assistant conversations are stored with the item. When the item is filed, they travel
with it: this module turns them into one block of text (selections quoted, `Q:` for the reader's
question, `A:` for the answer). The text is NOT made safe for any consumer here: answers come
from a model reading web text, so a caller that hands it to another program must fence it (the
MCP tool does, through `mcp_fence`).
"""

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.models import AssistMessage, AssistThread

# The most conversation text a tool returns for one item (the filing queue and `radar_get_item`).
QA_MAX = 6_000
_ACTION_LABELS = {"explain": "Explain this", "relevance": "How is this relevant to me",
                  "colleagues": "Draft a message for colleagues", "linkedin": "Draft a LinkedIn post",
                  "blog": "Outline a blog post"}
CUT_NOTE = "\n[The conversation was cut here.]"


def _lines(rows: list[AssistMessage]) -> list[str]:
    """Plain text lines for the messages of one thread."""
    lines: list[str] = []
    for row in rows:
        if row.role == "user":
            if row.selection and row.selection.strip():
                lines += [f"> {line}" for line in row.selection.strip().splitlines()]
            question = row.content.strip() or _ACTION_LABELS.get(row.action or "", row.action or "")
            lines += [f"Q: {question}", ""]
        elif row.content.strip():
            lines += [f"A: {row.content.strip()}", ""]
    return lines


def has_item_qa(session: Session, item_id: int) -> bool:
    """True when the reader has asked the assistant at least one question about the item."""
    row = session.exec(
        select(AssistMessage.id).join(AssistThread, AssistThread.id == AssistMessage.thread_id)
        .where(AssistThread.item_id == item_id, AssistMessage.role == "user").limit(1)).first()
    return row is not None


def item_qa_text(engine: Engine, item_id: int, limit: int, *, newest_first: bool = False) -> str:
    """Every conversation about the item as text of at most about `limit` characters.

    Conversations come oldest first, or newest first with `newest_first` so that a cut loses the
    oldest conversation and keeps the latest; the turns inside one conversation always keep their
    order. Returns "" when there is none. Longer text is cut at `limit` with a short note.
    """
    with Session(engine) as session:
        order = AssistThread.id.desc() if newest_first else AssistThread.id
        threads = session.exec(select(AssistThread).where(AssistThread.item_id == item_id)
                               .order_by(order)).all()
        lines: list[str] = []
        for thread in threads:
            rows = session.exec(select(AssistMessage).where(AssistMessage.thread_id == thread.id)
                                .order_by(AssistMessage.id)).all()
            lines += _lines(list(rows))
    text = "\n".join(lines).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + CUT_NOTE
