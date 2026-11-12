"""Long conversations: replace the earliest turns with a short written summary.

Two situations, one remedy.

An engine that keeps its own session (Claude Code, `--resume`) re-reads every earlier turn on every
question. That is cheap while it is cached, but the history grows by about 400 to 800 tokens a turn
(measured), and a long one is read again at a tenth of the price on each question, for as long as the
conversation lasts. Starting a fresh session from a summary costs one summary call and one write of the
summary, so it pays back only when the history is large. `LIMIT_TOKENS` is where it pays back within
about a dozen further questions: below it condensing costs more than it saves.

An engine without a session (the API engines) is sent the conversation on every turn, and the history
budget used to drop the oldest turns without a trace. The dropped turns are now summarised instead, with
the engine's cheaper model, and the summary is stored so it is made once, then extended only after
several more turns have been dropped.

The full conversation stays stored and visible either way; only what is sent to the model changes.
"""

import logging
from collections.abc import Callable, Iterable

from sqlalchemy import Engine as DbEngine
from sqlmodel import Session, select

from spyglass_service.radar.assist import context
from spyglass_service.radar.assist.engines.base import DELTA, DONE, ERROR, USAGE
from spyglass_service.radar.assist.model_choice import PAIRS
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.usage import UsageCall
from spyglass_service.radar.usage_parse import Tokens

logger = logging.getLogger(__name__)

# (system prompt, messages, model) -> the engine's events for one answer, with no session.
StreamRunner = Callable[[str, list[dict], str], Iterable]
# (messages to summarise, summary so far) -> (new summary, token figures of the call).
Summarizer = Callable[[list[dict], str | None], tuple[str | None, Tokens | None]]

# Growth, in tokens, of a resumed session's prompt since its first turn at which it is replaced.
LIMIT_TOKENS = 20_000
# With no token figures from the engine: stored messages (30 question-and-answer pairs) that trigger it.
FALLBACK_MESSAGES = 60
# How long the summary may be, in words.
SUMMARY_WORDS = 200
# A summary is made again only when this many more messages have fallen out of the history budget.
REFRESH_AFTER = 4
# The longest piece of one message, and of the whole transcript, handed to the summarising model.
_PIECE_CHARS = 2_000
_TRANSCRIPT_CHARS = 60_000
_KEY = "assist_summary:{thread_id}"
_SYSTEM = (
    "You condense the earlier part of a conversation between a reader and an assistant about an "
    "article, so that the assistant can carry on from your summary alone. Write at most "
    f"{SUMMARY_WORDS} words of plain sentences. Keep what the reader wanted, the questions they "
    "asked, the answers that were given, names, numbers, decisions and anything that was promised. "
    "Do not add anything that was not said. Reply with the summary only, with no preamble."
)


def history_growth(db: DbEngine, thread_id: int) -> int | None:
    """How many tokens the prompt of the thread's current session has grown since its first turn.

    From the usage table: the latest turn's prompt size minus the prompt size of the turn that
    started the session. None when either figure is not known. Rows recorded before the stored
    summary was made belong to the session it replaced and are ignored.
    """
    stored = load_summary(db, thread_id)
    floor = int(stored.get("usage_floor") or 0) if stored else 0
    try:
        with Session(db) as session:
            # Only the rows of answered turns: a summary call has none of its own message.
            rows = list(session.exec(select(UsageCall).where(
                UsageCall.thread_id == thread_id, UsageCall.message_id.is_not(None),
                UsageCall.id > floor).order_by(UsageCall.id)).all())
    except Exception:  # noqa: BLE001 -- no table yet means no figures
        return None
    if not rows:
        return None
    starts = [r for r in rows if r.fresh]
    start = starts[-1] if starts else None
    now = Tokens(input=rows[-1].input_tokens, cache_write=rows[-1].cache_write_tokens,
                 cache_read=rows[-1].cache_read_tokens).context
    base = (Tokens(input=start.input_tokens, cache_write=start.cache_write_tokens,
                   cache_read=start.cache_read_tokens).context if start else None)
    return None if now is None or base is None else now - base


def latest_usage_id(db: DbEngine, thread_id: int) -> int:
    """The id of the thread's newest usage row (0 when it has none or the table is missing)."""
    try:
        with Session(db) as session:
            newest = session.exec(select(UsageCall.id).where(UsageCall.thread_id == thread_id)
                                  .order_by(UsageCall.id.desc())).first()
    except Exception:  # noqa: BLE001 -- no table yet means no rows
        return 0
    return int(newest or 0)


def needs_condensing(db: DbEngine, thread_id: int, message_count: int) -> bool:
    """Whether a resumed session has grown past the limit (or, with no figures, is long).

    With no figures only the messages after the point the stored summary covers are counted: the
    count of all stored messages never falls, so counting them would condense on every turn.
    """
    growth = history_growth(db, thread_id)
    if growth is not None:
        return growth >= LIMIT_TOKENS
    stored = load_summary(db, thread_id)
    covered = int(stored.get("covers") or 0) if stored else 0
    return message_count - covered >= FALLBACK_MESSAGES


def cheap_model(engine_id: str, current: str) -> str:
    """The route's cheapest model for the summary: the engine's cheaper model when it has a known
    pair, else the model the conversation already uses."""
    return PAIRS[engine_id][0] if engine_id in PAIRS else current


def summary_messages(summary: str) -> list[dict]:
    """The summary as an opening reader turn and a short acknowledgement, so that the history
    starts with a reader message (some APIs reject anything else)."""
    return [{"role": "user", "content": "Earlier in this conversation (condensed to save usage):\n"
                                        + summary},
            {"role": "assistant", "content": "Understood. I will carry on from that."}]


def _transcript(messages: list[dict]) -> str:
    """The messages as a plain transcript, each piece and the whole kept within a size."""
    lines = [f"{'Reader' if m['role'] == 'user' else 'Assistant'}: {m['content'][:_PIECE_CHARS]}"
             for m in messages]
    return "\n\n".join(lines)[-_TRANSCRIPT_CHARS:]


def summarize(run: StreamRunner, model: str, earlier: list[dict],
              prior: str | None) -> tuple[str | None, Tokens | None]:
    """Ask for a summary of `earlier` (after `prior`, the summary so far, if any).

    `run(system, messages, model)` streams one answer from the conversation's engine; the caller
    supplies it so that the request passes the privacy layer like every other (see `threads`).
    Returns (text, token figures); (None, None) when the engine fails or says nothing.
    """
    transcript = _transcript(earlier)
    request = (f"Summary so far:\n{prior}\n\nNew messages:\n{transcript}" if prior
               else f"Conversation to condense:\n{transcript}")
    parts: list[str] = []
    tokens: Tokens | None = None
    try:
        for event in run(_SYSTEM, [{"role": "user", "content": request}], model):
            if event.kind == DELTA:
                parts.append(event.text)
            elif event.kind == USAGE:
                tokens = event.data
            elif event.kind == ERROR:
                logger.warning("could not condense a conversation: %s", event.text)
                return None, None
            elif event.kind == DONE:
                break
    except Exception:  # noqa: BLE001 -- a summary is an optimisation, never a reason to fail the turn
        logger.exception("could not condense a conversation")
        return None, None
    text = "".join(parts).strip()
    return (text, tokens) if text else (None, None)


def load_summary(db: DbEngine, thread_id: int) -> dict | None:
    """The stored summary {"covers": n, "text": ...} of a thread, or None."""
    with Session(db) as session:
        row = session.get(RadarDoc, _KEY.format(thread_id=thread_id))
    doc = loads(row.body if row else None, None)
    return doc if isinstance(doc, dict) and isinstance(doc.get("text"), str) else None


def save_summary(db: DbEngine, thread_id: int, covers: int, text: str,
                 usage_floor: int | None = None) -> None:
    """Store that the first `covers` messages of the thread are summarised by `text`.

    `usage_floor` is the newest usage row id when a session was replaced by the summary; the
    growth of the new session is measured from the rows after it. None keeps the stored value.
    """
    key = _KEY.format(thread_id=thread_id)
    with Session(db) as session:
        row = session.get(RadarDoc, key)
        if usage_floor is None:
            old = loads(row.body if row else None, None)
            usage_floor = int(old.get("usage_floor") or 0) if isinstance(old, dict) else 0
        body = dumps({"covers": covers, "text": text, "usage_floor": usage_floor})
        if row is None:
            row = RadarDoc(key=key, body=body)
        else:
            row.body, row.updated_at = body, utcnow()
        session.add(row)
        session.commit()


def condense_session(db: DbEngine, thread_id: int, messages: list[dict],
                     summarizer: Summarizer) -> list[dict] | None:
    """The messages for a fresh session that replaces a long resumed one: the summary of every
    earlier message, then the new question. None when no summary could be made."""
    earlier = messages[:-1]
    stored = load_summary(db, thread_id)
    covers = min(int(stored["covers"]), len(earlier)) if stored else 0
    made, _figures = summarizer(earlier[covers:], stored["text"] if stored else None)
    if not made:
        return None
    save_summary(db, thread_id, len(earlier), made, usage_floor=latest_usage_id(db, thread_id))
    return [*summary_messages(made), messages[-1]]


def _to_user_turn(messages: list[dict], index: int) -> int:
    """`index`, moved forward to the next message from the reader (a history starts with one)."""
    while index < len(messages) and messages[index]["role"] != "user":
        index += 1
    return index



def fit_history(db: DbEngine, thread_id: int, messages: list[dict], summarizer: Summarizer,
                budget: int = context.HISTORY_BUDGET) -> tuple[list[dict], bool]:
    """The messages to send when the engine has no session: the newest that fit `budget`, and a
    summary of the older ones instead of nothing.

    `summarizer(earlier, prior)` returns (text, figures); it is called only when the stored summary
    is missing or `REFRESH_AFTER` messages behind. Returns (messages, whether a summary is in them).
    When no summary can be made the older messages are simply dropped, as before.
    """
    kept = context.trim_history(messages, budget)
    dropped = len(messages) - len(kept)
    if dropped <= 0:
        return messages, False
    stored = load_summary(db, thread_id)
    covers = int(stored["covers"]) if stored else 0
    text = stored["text"] if stored else None
    if text is None or dropped - covers >= REFRESH_AFTER:
        end = _to_user_turn(messages, dropped)
        made, _figures = summarizer(messages[covers:end], text)
        if made:
            text, covers = made, end
            save_summary(db, thread_id, covers, text)
    if text is None:
        return kept, False
    covers = _to_user_turn(messages, min(covers, dropped))
    return [*summary_messages(text), *messages[covers:]], True
