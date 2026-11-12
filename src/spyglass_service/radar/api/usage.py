"""GET /api/radar/usage: what the model calls used in the last few days."""

from fastapi import APIRouter, HTTPException, Query, Request
from sqlmodel import Session, select

from spyglass_service.radar.assist.turn_usage import usage_payload
from spyglass_service.radar.usage import UsageCall, ensure_table
from spyglass_service.radar.usage_parse import Tokens
from spyglass_service.radar.usage_report import build_report

router = APIRouter()

# The longest window the report offers; rows older than 180 days are pruned by the weekly upkeep.
MAX_DAYS = 180


@router.get("/usage")
def get_usage(request: Request, days: int = Query(default=7, ge=1, le=MAX_DAYS)) -> dict:
    """Totals per day and per purpose and model, the cached share and the ten most expensive
    conversations, for the last `days` days."""
    engine = request.app.state.engine
    # The table is created by init_db and by the first recorded call; a database that has neither
    # yet simply has no usage to report.
    ensure_table(engine)
    return build_report(engine, days)


@router.get("/usage/messages/{message_id}")
def get_message_usage(message_id: int, request: Request) -> dict:
    """The token figures of the turn that produced a stored answer (404 when none were kept).

    Keys as in the chat `done` event's `usage`, plus `condensed` when the turn started from a
    short summary of the earlier conversation.
    """
    engine = request.app.state.engine
    ensure_table(engine)
    with Session(engine) as session:
        row = session.exec(select(UsageCall).where(UsageCall.message_id == message_id)
                           .order_by(UsageCall.id.desc())).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No usage was recorded for that answer.")
    figures = usage_payload(Tokens(input=row.input_tokens, cache_write=row.cache_write_tokens,
                                   cache_read=row.cache_read_tokens, output=row.output_tokens,
                                   cost_usd=row.cost_usd)) or {}
    return {**figures, "model": row.model, "provider": row.provider,
            **({"condensed": True} if row.condensed else {})}
