"""Assistant threads: create or reuse one, store its messages, and run one streamed turn.

`run_turn` is a generator of plain event dicts (the same objects the SSE endpoint sends):
  {"type": "delta", "text": ...}   a piece of the answer
  {"type": "ping"}                 nothing new yet (lets the caller check for a disconnect)
  {"type": "done", "message_id": n}   the answer was stored
  {"type": "error", "message": ...}   the engine failed; the partial answer was stored with the error
The reader's message is stored before any streaming starts. If the generator is closed early
(the reader closed the panel), the partial answer is stored with the error "Stopped".
"""

import logging
import time
from collections.abc import Callable, Iterator

import httpx
from sqlalchemy import Engine as DbEngine
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.radar.agy_cli import TOOL_REFUSED
from spyglass_service.radar.assist import condense, context, feed_context, model_choice, registry
from spyglass_service.radar.assist.engines.antigravity import TOOL_AFTER_TEXT
from spyglass_service.radar.assist.engines.base import DELTA, DONE, ERROR, PING, SESSION, USAGE
from spyglass_service.radar.assist.turn_usage import record_summary, record_turn, usage_payload
from spyglass_service.radar.models import AssistMessage, AssistThread, Signal, utcnow
from spyglass_service.radar.privacy import fence, prepare_assistant_call

logger = logging.getLogger(__name__)

_TITLE_CHARS = 60
_STOPPED = "Stopped before the answer was finished."
# The two messages an engine ends a turn with when the model tried to use a tool.
_TOOL_REFUSED_ERRORS = frozenset({TOOL_REFUSED, TOOL_AFTER_TEXT})


class ThreadNotFound(LookupError):
    """No thread has that id."""


def _iso(value) -> str | None:
    """ISO text for a timestamp or None."""
    return value.isoformat() if value else None


def thread_dict(thread: AssistThread) -> dict:
    """The API shape of a thread."""
    return {"id": thread.id, "item_id": thread.item_id, "brief_day": thread.brief_day,
            "title": thread.title, "engine": thread.engine, "model": thread.model,
            "created_at": _iso(thread.created_at), "updated_at": _iso(thread.updated_at)}


def message_dict(message: AssistMessage) -> dict:
    """The API shape of a message."""
    return {"id": message.id, "role": message.role, "content": message.content,
            "selection": message.selection, "action": message.action, "engine": message.engine,
            "model": message.model, "error": message.error, "created_at": _iso(message.created_at)}


def create_or_get_thread(db: DbEngine, *, item_id: int | None = None, brief_day: str | None = None,
                         new: bool = False) -> dict:
    """The latest thread for the target, or a fresh one when none exists or `new` is true."""
    with Session(db) as session:
        if not new:
            query = select(AssistThread).where(
                AssistThread.item_id == item_id if item_id is not None
                else AssistThread.item_id.is_(None),
                AssistThread.brief_day == brief_day if brief_day
                else AssistThread.brief_day.is_(None))
            latest = session.exec(
                query.order_by(AssistThread.updated_at.desc(), AssistThread.id.desc())).first()
            if latest is not None:
                return thread_dict(latest)
        thread = AssistThread(item_id=item_id, brief_day=brief_day)
        session.add(thread)
        session.commit()
        session.refresh(thread)
        return thread_dict(thread)


def thread_detail(db: DbEngine, thread_id: int) -> dict | None:
    """{"thread", "messages"} for a thread, or None when it does not exist.

    A thread about the feed also has "retrieved": [{"id", "headline"}] for the items cited so far.
    """
    with Session(db) as session:
        thread = session.get(AssistThread, thread_id)
        if thread is None:
            return None
        rows = session.exec(select(AssistMessage).where(AssistMessage.thread_id == thread_id)
                            .order_by(AssistMessage.id)).all()
        detail = {"thread": thread_dict(thread), "messages": [message_dict(m) for m in rows]}
        about_feed = thread.item_id is None and not thread.brief_day
    if about_feed:
        # A conversation about the feed: the headlines its answers can cite.
        detail["retrieved"] = feed_context.thread_retrieved(db, thread_id)
    return detail


def _resolve(settings: Settings, session: Session, thread: AssistThread, engine_id: str | None,
             model: str | None, transport: httpx.BaseTransport | None, *, action: str | None = None,
             content: str = ""):
    """Pick (engine object or None, engine id, model, problem text) for this turn.

    The model "auto" becomes the engine's cheaper or stronger model for this action and question
    (see `model_choice`); the answer records the model that was used.
    """
    rows = registry.list_engines(settings, session, transport)
    default = next((r for r in rows if r.get("is_default")), None)
    wanted = engine_id or thread.engine or (default["id"] if default else None)
    row = next((r for r in rows if r["id"] == wanted), None)
    if row is None:
        return None, wanted, model, "No assistant engine is set up yet. Add one in the settings."
    chosen_model = model or (thread.model if wanted == thread.engine else None) \
        or row["default_model"]
    if chosen_model == model_choice.AUTO:
        chosen_model = (model_choice.choose(wanted, action, content) if model_choice.offers_auto(wanted)
                        else row["default_model"])
    if not row["available"]:
        return None, wanted, chosen_model, f"{row['label']} is not available: {row['reason']}"
    return registry.get_engine(settings, wanted, session, transport), wanted, chosen_model, None


def _store_user_turn(session: Session, thread: AssistThread, content: str, selection: str | None,
                     action: str | None, engine_id: str | None, model: str | None) -> list[dict]:
    """Save the reader's message, update the thread, and return the chat history for the engine."""
    prior = session.exec(select(AssistMessage).where(AssistMessage.thread_id == thread.id)
                         .order_by(AssistMessage.id)).all()
    history = [
        {"role": m.role, "content": context.build_turn(m.content, m.selection, m.action)
         if m.role == "user" else m.content}
        for m in prior if not (m.role == "assistant" and (m.error and not m.content))
    ]
    session.add(AssistMessage(thread_id=thread.id, role="user", content=content,
                              selection=selection, action=action))
    if not thread.title:
        first = content.strip() or (action or "")
        thread.title = " ".join(first.split())[:_TITLE_CHARS]
    thread.engine, thread.model, thread.updated_at = engine_id, model, utcnow()
    session.add(thread)
    session.add(Signal(item_id=thread.item_id, kind="ask", value=action or "question"))
    session.commit()
    return [*history, {"role": "user", "content": context.build_turn(content, selection, action)}]


def _store_answer(db: DbEngine, thread_id: int, text: str, error: str | None, engine_id: str | None,
                  model: str | None, external_session: str | None, *,
                  clear_session: bool = False) -> int:
    """Save the assistant message (possibly partial) and the thread's session id; return its id.

    A given `external_session` replaces the stored one; `clear_session` forgets the stored one
    when none is given (the session it named was replaced by a condensed one that has no id yet).
    """
    with Session(db) as session:
        message = AssistMessage(thread_id=thread_id, role="assistant", content=text, error=error,
                                engine=engine_id, model=model)
        session.add(message)
        thread = session.get(AssistThread, thread_id)
        if thread is not None:
            if external_session:
                thread.external_session = external_session
            elif clear_session:
                thread.external_session = None
            thread.updated_at = utcnow()
            session.add(thread)
        session.commit()
        session.refresh(message)
        return message.id


def _feed_turn(db: DbEngine, thread_id: int, index_provider: Callable[[], object] | None, *,
               content: str, selection: str | None, action: str | None) -> tuple[str, list[dict]]:
    """The retrieved-items text for a feed thread's turn, and the headlines of those items.

    Also remembers the retrieved ids on the thread. A missing or failing embedding index is
    logged and the retrieval falls back to text matches; any other failure is raised.
    """
    index = None
    if index_provider is not None:
        try:
            index = index_provider()
        except Exception:  # noqa: BLE001 -- the index is optional context
            logger.exception("The embedding index is unavailable; searching the feed by text only")
    question = content.strip() or context.ACTIONS.get(action or "", "")
    block, ids = feed_context.build_feed_block(
        db, index, question=question, selection=selection, action=action)
    feed_context.remember_retrieved(db, thread_id, ids)
    return block, feed_context.headlines(db, ids)


def _with_passages(db: DbEngine, item_id: int, messages: list[dict], question: str,
                   index_provider: Callable[[], object] | None) -> list[dict]:
    """The messages with, for an article longer than the text budget, the passages closest to the
    question put in front of the last one. Only a turn that sends the instructions can carry them:
    a resumed session keeps what its first turn was given."""
    block = context.long_item_passages(db, item_id, question, index_provider)
    if not block or not messages:
        return messages
    last = messages[-1]
    return [*messages[:-1], {**last, "content": fence(block) + "\n\n" + last["content"]}]


def run_turn(db: DbEngine, settings: Settings, thread_id: int, *, content: str,
             selection: str | None = None, action: str | None = None,
             engine_id: str | None = None, model: str | None = None,
             transport: httpx.BaseTransport | None = None,
             index_provider: Callable[[], object] | None = None) -> Iterator[dict]:
    """Store the reader's message, stream the engine's answer, store it; see the module docstring.

    `index_provider` returns the embedding index; a thread about the feed uses it to find the
    items related to the question (its `done` event then carries `retrieved`, the headlines of
    the items listed to the model). Raises ThreadNotFound (before yielding anything) for an
    unknown thread.
    """
    with Session(db) as session:
        thread = session.get(AssistThread, thread_id)
        if thread is None:
            raise ThreadNotFound(thread_id)
        engine, used_engine, used_model, problem = _resolve(
            settings, session, thread, engine_id, model, transport, action=action, content=content)
        switched = used_engine != thread.engine
        external = None if switched else thread.external_session
        messages = _store_user_turn(session, thread, content, selection, action,
                                    used_engine, used_model)
        item_id, brief_day = thread.item_id, thread.brief_day
    if engine is None:
        _store_answer(db, thread_id, "", problem, used_engine, used_model, None)
        yield {"type": "error", "message": problem}
        return
    feed_block: str | None = None
    extra: dict = {}
    if item_id is None and not brief_day:
        try:
            feed_block, retrieved = _feed_turn(db, thread_id, index_provider, content=content,
                                               selection=selection, action=action)
        except Exception:  # noqa: BLE001 -- the reader gets a short message, the log gets the cause
            logger.exception("Could not search the feed for thread %s", thread_id)
            message = "Could not search the feed just now."
            _store_answer(db, thread_id, "", message, used_engine, used_model, None)
            yield {"type": "error", "message": message}
            return
        extra = {"retrieved": retrieved}
    system = context.build_system(db, item_id=item_id, brief_day=brief_day, selection=selection,
                                  feed_block=feed_block)
    # The seam: secrets and personal details out, the item's text fenced, before the engine sees it.
    about_feed = item_id is None and not brief_day
    cheap = condense.cheap_model(used_engine or "", used_model or "")

    def run_summary(summary_system: str, summary_messages: list[dict], summary_model: str):
        """One engine answer for the summary request, after the same privacy step as a turn."""
        clean_system, clean = prepare_assistant_call(summary_system, summary_messages, settings)
        return engine.stream(system=clean_system, messages=clean, model=summary_model, session=None)

    def summarizer(earlier: list[dict], prior: str | None):
        """Summarise `earlier` with the route's cheaper model and keep the call's usage row."""
        began = time.monotonic()
        text, figures = condense.summarize(run_summary, cheap, earlier, prior)
        if text:
            record_summary(db, thread_id=thread_id, about_feed=about_feed, engine=used_engine,
                           model=cheap, tokens=figures, started=began)
        return text, figures

    condensed = False
    replaced = False  # the old session was replaced by a fresh one that carries a summary
    if external is not None and condense.needs_condensing(db, thread_id, len(messages)):
        fresh_messages = condense.condense_session(db, thread_id, messages, summarizer)
        if fresh_messages is not None:  # a new session carries the summary; the old one is left
            messages, external, condensed, replaced = fresh_messages, None, True, True
    if external is None:
        trimmed, summarised = condense.fit_history(db, thread_id, messages, summarizer)
        condensed = condensed or summarised
    else:
        trimmed = context.trim_history(messages)
    if item_id is not None and external is None:
        trimmed = _with_passages(db, item_id, trimmed, content or context.ACTIONS.get(action or "", ""),
                                 index_provider)
    system, sent = prepare_assistant_call(system, trimmed, settings)
    started = time.monotonic()
    stream = engine.stream(system=system, messages=sent, model=used_model or "", session=external)
    parts: list[str] = []
    new_session: str | None = None
    tokens = None
    finished = False

    def store_unfinished(text: str, error: str) -> None:
        """Store a failed or stopped answer. After a condense the thread must not keep pointing at
        the over-limit session it replaced, or the next turn would condense again: it keeps the
        new session's id when one was reported, else forgets the old one."""
        _store_answer(db, thread_id, text, error, used_engine, used_model,
                      new_session if replaced else None, clear_session=replaced)

    def complete() -> dict:
        """Store the answer and its usage; the `done` event for the reader."""
        message_id = _store_answer(db, thread_id, "".join(parts), None, used_engine, used_model,
                                   new_session)
        own = record_turn(db, thread_id=thread_id, message_id=message_id,
                          about_feed=about_feed, engine=used_engine,
                          model=used_model, tokens=tokens, started=started,
                          resumed=external is not None, condensed=condensed)
        figures = usage_payload(own, condensed)
        return {"type": "done", **extra, "message_id": message_id, **({"usage": figures} if figures else {})}

    try:
        for event in stream:
            if event.kind == DELTA:
                parts.append(event.text)
                yield {"type": "delta", "text": event.text}
            elif event.kind == SESSION:
                new_session = event.text
            elif event.kind == USAGE:
                tokens = event.data
            elif event.kind == PING:
                yield {"type": "ping"}
            elif event.kind == DONE:
                finished = True
                yield complete()
                return
            elif event.kind == ERROR:
                finished = True
                # Text streamed before a refused tool attempt is not to be relied on: drop it.
                kept = "" if event.text in _TOOL_REFUSED_ERRORS else "".join(parts)
                store_unfinished(kept, event.text)
                yield {"type": "error", "message": event.text}
                return
        finished = True  # the engine ended without done or error: treat the text as the answer
        yield complete()
    except Exception:  # noqa: BLE001 -- an engine bug must reach the reader as a short message
        logger.exception("The assistant engine %s failed", used_engine)
        finished = True
        store_unfinished("".join(parts), "The assistant failed unexpectedly.")
        yield {"type": "error", "message": "The assistant failed unexpectedly."}
    finally:
        stream.close()
        if not finished:
            store_unfinished("".join(parts), _STOPPED)
