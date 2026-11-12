"""What a chat turn reports about its own token use: the figures in the `done` event and the row
kept in the usage table.
"""

import time
from dataclasses import replace

from sqlalchemy import Engine as DbEngine
from sqlmodel import Session, select

from spyglass_service.radar import usage
from spyglass_service.radar.usage_parse import Tokens


def usage_payload(tokens: Tokens | None, condensed: bool = False) -> dict | None:
    """The figures as the `done` event and the interface carry them, or None when unknown.

    Keys: input_tokens (outside the cache), cache_write_tokens, cache_read_tokens, output_tokens,
    context_tokens (the whole prompt), cached_share (0 to 1) and cost_usd (the provider's figure).
    Parts the provider did not report are left out. `condensed` adds "condensed": true, for a
    turn that started from a short summary of the earlier conversation.
    """
    if tokens is None:
        return {"condensed": True} if condensed else None
    figures = {"input_tokens": tokens.input, "cache_write_tokens": tokens.cache_write,
               "cache_read_tokens": tokens.cache_read, "output_tokens": tokens.output,
               "context_tokens": tokens.context, "cached_share": tokens.cached_share,
               "cost_usd": tokens.cost_usd}
    out = {key: value for key, value in figures.items() if value is not None}
    return {**out, "condensed": True} if condensed else out


def own_cost(db: DbEngine, thread_id: int, reported: float | None, resumed: bool) -> float | None:
    """This turn's share of a cost the provider reported.

    Claude Code reports the cost of the whole conversation on a resumed turn, so the share is the
    reported figure minus the one reported on the turn before. A new session, or a figure lower than
    the last one (the session was lost and restarted), counts in full.
    """
    if reported is None or not resumed:
        return reported
    try:
        with Session(db) as session:
            previous = session.exec(select(usage.UsageCall.cost_total).where(
                usage.UsageCall.thread_id == thread_id, usage.UsageCall.cost_total.is_not(None))
                .order_by(usage.UsageCall.id.desc())).first()
    except Exception:  # noqa: BLE001 -- the table may not exist yet; then there is no earlier turn
        return reported
    return reported if previous is None or reported < previous else reported - previous


def record_summary(db: DbEngine, *, thread_id: int, about_feed: bool, engine: str | None, model: str,
                   tokens: Tokens | None, started: float) -> None:
    """Store the row of the call that condensed a conversation (it has no answer of its own)."""
    usage.record_call(
        db, purpose="feed_chat" if about_feed else "chat", provider=engine or "unknown", model=model,
        tokens=tokens, duration_ms=int((time.monotonic() - started) * 1000), thread_id=thread_id)


def record_turn(db: DbEngine, *, thread_id: int, message_id: int, about_feed: bool, engine: str | None,
                model: str | None, tokens: Tokens | None, started: float, resumed: bool = False,
                condensed: bool = False) -> Tokens | None:
    """Store the turn's row in the usage table and return the figures with this turn's own cost.

    `started` is a `time.monotonic()` reading; `resumed` says the engine continued its own session.
    """
    reported = tokens.cost_usd if tokens is not None else None
    if tokens is not None and tokens.cost_usd is not None:
        tokens = replace(tokens, cost_usd=own_cost(db, thread_id, tokens.cost_usd, resumed))
    usage.record_call(
        db, purpose="feed_chat" if about_feed else "chat", provider=engine or "unknown",
        model=model or "", tokens=tokens, duration_ms=int((time.monotonic() - started) * 1000),
        thread_id=thread_id, message_id=message_id, condensed=condensed, fresh=not resumed,
        cost_total=reported)
    return tokens
